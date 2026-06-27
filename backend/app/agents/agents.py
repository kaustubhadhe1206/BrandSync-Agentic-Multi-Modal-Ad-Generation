"""The agent definitions. Three primary agents + a critic role used inside a loop.

The Strategist <-> Critic loop is what makes this genuinely agentic rather than
a pipeline: the Critic agent can REJECT a brief and force the Strategist to
revise, up to MAX_CRITIQUE_ITERATIONS. Both run on Claude (settings.MODEL_CRITIQUE)
since this is a negotiation, not generation — the Strategist can push back on a
critique with a `rebuttal` instead of just complying (see agents/tools.py
submit_brief). Every other agent stays on Gemini; only Director/Post-Production's
tools call the actual Gemini/Veo/Lyria/TTS generation models.

Architecture:

    Strategist  ──┐
                  │ writes brief
                  ▼
              Critic (LoopAgent guard)
                  │ accept? if no → back to Strategist with feedback
                  ▼
          Creative Director
                  │ generates assets
                  ▼
          Post-Production
                  │ produces final video
                  ▼
                Done
"""
from __future__ import annotations

import json
import re
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.anthropic_llm import AnthropicLlm

from ..config import settings
from . import prompts
from . import tools as agent_tools

# ADK's model registry auto-resolves any plain "claude-*" string to the
# `Claude` class specifically, which is the VERTEX AI variant (needs
# GOOGLE_CLOUD_PROJECT/GOOGLE_CLOUD_LOCATION) — not the direct-API
# `AnthropicLlm` base class that just needs ANTHROPIC_API_KEY. Constructing
# AnthropicLlm explicitly bypasses that registry resolution so this hits
# Anthropic's API directly with no Google Cloud project involved.
_critique_model = AnthropicLlm(model=settings.MODEL_CRITIQUE)


# ────────────────────────────────────────────────────────────────────────────
# 1. STRATEGIST — ingests URL, writes BrandBrief
# ────────────────────────────────────────────────────────────────────────────
strategist_agent = LlmAgent(
    name="strategist",
    model=_critique_model,
    description="Reads a website and produces a detailed creative brief for the video ad.",
    instruction=prompts.STRATEGIST_INSTRUCTION,
    tools=[
        agent_tools.scrape_website,
        agent_tools.submit_brief,
    ],
    output_key="strategist_output",
)


# ────────────────────────────────────────────────────────────────────────────
# 2. CRITIC — internal QA role used inside the critique loop
# ────────────────────────────────────────────────────────────────────────────
critic_agent = LlmAgent(
    name="critic",
    model=_critique_model,
    description="Evaluates whether a brief from the Strategist is workable.",
    instruction=prompts.CRITIC_INSTRUCTION,
    output_key="director_critique",
)


def _parse_critique(raw) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None
    return None


class CritiqueGate(BaseAgent):
    """Breaks brief_loop early once the Critic accepts the brief.

    Without this, LoopAgent always runs MAX_CRITIQUE_ITERATIONS rounds even
    when the Critic accepted on round 1 — doubling Strategist+Critic LLM
    spend on the common case. Yielding an Event with actions.escalate=True
    tells LoopAgent to stop after this sub-agent's turn.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        critique = _parse_critique(ctx.session.state.get("director_critique"))
        if critique and critique.get("accept"):
            yield Event(author=self.name, actions=EventActions(escalate=True))


critique_gate = CritiqueGate(name="critique_gate")


# ────────────────────────────────────────────────────────────────────────────
# 2b. STRATEGIST <-> CRITIC LOOP
# The LoopAgent runs strategist→critic up to MAX_CRITIQUE_ITERATIONS, but
# critique_gate breaks it early the moment the Critic accepts.
# ────────────────────────────────────────────────────────────────────────────
brief_loop = LoopAgent(
    name="brief_with_critique",
    description="Strategist writes a brief; Critic accepts or requests revisions.",
    max_iterations=settings.MAX_CRITIQUE_ITERATIONS,
    sub_agents=[strategist_agent, critic_agent, critique_gate],
)


# ────────────────────────────────────────────────────────────────────────────
# 3. CREATIVE DIRECTOR — turns the brief into images + music + voiceover
# ────────────────────────────────────────────────────────────────────────────
creative_director_agent = LlmAgent(
    name="creative_director",
    model=settings.MODEL_BRAIN,
    description="Turns an approved brief into hero image, music, and voiceover.",
    instruction=prompts.DIRECTOR_INSTRUCTION,
    tools=[
        agent_tools.generate_image_prompts,
        agent_tools.generate_and_rank_images,
        agent_tools.generate_music_and_voiceover,
        agent_tools.package_assets,
    ],
    output_key="director_output",
)


# ────────────────────────────────────────────────────────────────────────────
# 3b. CREATIVE DIRECTOR (IMAGES ONLY) — scoped feedback re-runs
# Deliberately has no music/voiceover/package_assets tools, so it CANNOT
# regenerate those even if its instruction were ignored — scoping is
# enforced by tool availability, not just prose. Used when the Supervisor's
# asset_scope says feedback is visual-only, so a "make it Pixar style"
# request doesn't also burn a fresh Lyria + TTS call for audio that didn't
# need to change.
# ────────────────────────────────────────────────────────────────────────────
creative_director_images_agent = LlmAgent(
    name="creative_director_images",
    model=settings.MODEL_BRAIN,
    description="Regenerates just the candidate images per feedback; cannot touch music or voiceover.",
    instruction=prompts.DIRECTOR_IMAGES_ONLY_INSTRUCTION,
    tools=[
        agent_tools.generate_image_prompts,
        agent_tools.generate_and_rank_images,
    ],
    output_key="director_images_output",
)


# ────────────────────────────────────────────────────────────────────────────
# 4. POST-PRODUCTION — Veo video + FFmpeg mux
# ────────────────────────────────────────────────────────────────────────────
post_production_agent = LlmAgent(
    name="post_production",
    model=settings.MODEL_BRAIN,
    description="Produces the final video from the asset bundle.",
    instruction=prompts.POST_PRODUCTION_INSTRUCTION,
    tools=[
        agent_tools.generate_motion_prompts,
        agent_tools.generate_veo_video,
        agent_tools.sync_final_video,
    ],
    output_key="post_production_output",
)


# ────────────────────────────────────────────────────────────────────────────
# 5. SUPERVISOR — top-level orchestrator + feedback router
# ────────────────────────────────────────────────────────────────────────────
supervisor_agent = LlmAgent(
    name="supervisor",
    model=settings.MODEL_FAST,
    description="Routes user feedback to the correct agent.",
    instruction=prompts.SUPERVISOR_INSTRUCTION,
    output_key="supervisor_decision",
)


# Export the full pipeline as a SequentialAgent for convenience
brandsync_pipeline = SequentialAgent(
    name="brandsync_pipeline",
    description="Full BrandSync pipeline: brief → assets → video.",
    sub_agents=[brief_loop, creative_director_agent, post_production_agent],
)
