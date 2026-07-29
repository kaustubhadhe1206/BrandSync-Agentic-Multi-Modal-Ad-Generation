"""Pipeline orchestrator. Runs the ADK agents and translates ADK events into
SessionEvents that the frontend can render.

This is where the agentic-vs-pipeline architectural choice gets concrete:
we use ADK's Runner so the agent loop is real (the LLM decides when to call
tools, when to hand off, etc.), but we wrap it in our own session/event layer
so the frontend sees a live "control room" of what each agent is doing.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Any

from google import genai
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from ..agents import (
    brief_loop,
    creative_director_agent,
    creative_director_images_agent,
    post_production_agent,
    strategist_agent,
    supervisor_agent,
)
from ..config import settings
from ..storage import Session, cloud_cache
from ..tools import generate_music, generate_voiceover, sync_video_audio


_APP_NAME = "brandsync"
_USER_ID = "default_user"


async def _run_agent(
    agent,
    user_message: str,
    session: Session,
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a single ADK agent and stream its events into the session queue.

    Returns the final state dict (so the next agent can seed from it).
    """
    svc = InMemorySessionService()
    adk_session = await svc.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        state=initial_state or {},
    )

    runner = Runner(
        app_name=_APP_NAME,
        agent=agent,
        session_service=svc,
    )

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)],
    )

    async for event in runner.run_async(
        user_id=_USER_ID,
        session_id=adk_session.id,
        new_message=content,
    ):
        await _translate_event(event, agent.name, session)

    # Pull the final state out of the ADK session
    final = await svc.get_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        session_id=adk_session.id,
    )
    return dict(final.state) if final else {}


async def _translate_event(adk_event, default_agent: str, session: Session) -> None:
    """Convert an ADK Event into one or more SessionEvents."""
    author = getattr(adk_event, "author", None) or default_agent

    if not adk_event.content or not adk_event.content.parts:
        return

    for part in adk_event.content.parts:
        # Tool calls
        if getattr(part, "function_call", None):
            fc = part.function_call
            await session.emit(
                author,
                "tool_call",
                f"Calling {fc.name}",
                tool_name=fc.name,
                args=dict(fc.args or {}),
            )
            continue

        # Tool results
        if getattr(part, "function_response", None):
            fr = part.function_response
            await session.emit(
                author,
                "tool_result",
                f"{fr.name} returned",
                tool_name=fr.name,
                response=dict(fr.response or {}),
            )
            continue

        # Plain text — the agent's reasoning / message
        if getattr(part, "text", None):
            text = part.text.strip()
            if text:
                await session.emit(author, "message", text)


# ────────────────────────────────────────────────────────────────────────────
# Pipeline phases — each one is resumable: run_full_pipeline runs all three,
# resume_pipeline runs only the ones whose output is missing from state, so a
# failure partway through doesn't force re-paying for already-succeeded stages.
# ────────────────────────────────────────────────────────────────────────────

async def _run_strategist_phase(session: Session, url: str) -> None:
    # Persisted immediately (not just seeded into the ADK sub-session) so it
    # survives even if this phase fails outright — resume_pipeline needs it.
    session.state["source_url"] = url

    await session.emit("system", "handoff", "→ Brand Strategist taking over", phase="strategist")
    state = await _run_agent(
        brief_loop,
        user_message=f"The user wants a video ad for: {url}",
        session=session,
        initial_state={**session.state, "session_id": session.id},
    )
    session.state.update(state)

    # If the critic rejected on the last iteration, surface it but continue
    # (the LoopAgent already gave the strategist its chances)
    critique = _parse_critique(state.get("director_critique"))
    if critique and not critique.get("accept", True):
        await session.emit(
            "creative_director",
            "message",
            f"Brief still has issues after {state.get('critique_round', 0)} rounds, "
            f"but proceeding: {critique.get('reason', '')}",
        )

    if "brand_brief" not in state:
        raise RuntimeError("Strategist failed to produce a brief")

    await session.emit(
        "strategist",
        "message",
        f"Brief locked: {state['brand_brief']['business_name']}",
        brief=state["brand_brief"],
        phase="strategist",
    )


async def _run_director_phase(session: Session) -> None:
    await session.emit("system", "handoff", "→ Creative Director taking over", phase="creative_director")
    state = await _run_agent(
        creative_director_agent,
        user_message="Produce all creative assets per the brief in state.",
        session=session,
        initial_state=session.state,
    )
    session.state.update(state)
    if "asset_bundle" not in state:
        raise RuntimeError("Creative Director failed to produce an asset bundle")
    await session.emit(
        "creative_director",
        "message",
        "Asset bundle ready",
        asset_bundle=state["asset_bundle"],
        phase="creative_director",
    )


async def _run_post_production_phase(session: Session) -> None:
    await session.emit("system", "handoff", "→ Post-Production taking over", phase="post_production")
    state = await _run_agent(
        post_production_agent,
        user_message="Produce the final video from the asset bundle.",
        session=session,
        initial_state=session.state,
    )
    session.state.update(state)
    if "final_video_path" not in state:
        raise RuntimeError("Post-Production failed to produce final video")

    await session.emit(
        "post_production",
        "done",
        "Final video ready",
        final_video_path=state["final_video_path"],
        duration_sec=state.get("final_duration"),
        phase="post_production",
    )


async def _apply_cached_result(session: Session, cached: dict[str, Any]) -> None:
    """Populate session.state from a cache hit and emit the same event shapes
    a live run would, so the frontend renders identically — just instantly
    and for free."""
    await session.emit(
        "system", "message",
        "Found a cached generation for this URL — skipping regeneration.",
    )
    session.state.update({
        "brand_brief": cached.get("brand_brief"),
        "asset_bundle": cached.get("asset_bundle"),
        "ranked_images": cached.get("ranked_images"),
        "final_video_path": cached.get("final_video_path"),
        "final_duration": cached.get("final_duration"),
    })
    await session.emit(
        "strategist", "message",
        f"Brief locked: {cached['brand_brief']['business_name']} (cached)",
        brief=cached["brand_brief"],
        phase="strategist",
    )
    await session.emit(
        "creative_director", "message", "Asset bundle ready (cached)",
        asset_bundle=cached["asset_bundle"],
        phase="creative_director",
    )
    await session.emit(
        "post_production", "done", "Final video ready (cached)",
        final_video_path=cached["final_video_path"],
        duration_sec=cached.get("final_duration"),
        phase="post_production",
    )


async def _cache_lookup(url: str) -> dict[str, Any] | None:
    try:
        return await cloud_cache.get(url)
    except Exception:
        return None  # cache issues should never block a real generation


async def _cache_save(session: Session, url: str) -> None:
    try:
        await cloud_cache.put(url, session.id, session.state)
    except Exception as e:
        await session.emit("system", "message", f"Cache write skipped: {e}")
    _cleanup_local_artifacts(session.id)


def _cleanup_local_artifacts(session_id: str) -> None:
    """Remove this session's local scratch directory now that everything it
    contained has already been uploaded individually as it was produced.
    Only when Supabase is actually configured — local disk IS the storage
    when it isn't, so there's nothing to clean up in that case."""
    if not cloud_cache.is_configured:
        return
    shutil.rmtree(settings.OUTPUT_DIR / session_id, ignore_errors=True)


async def run_full_pipeline(session: Session, url: str, force_regenerate: bool = False, creative_direction: str = "") -> None:
    """Run Strategist→Critic→Director→Post-Production end-to-end.

    Checks the cloud cache first (unless force_regenerate) — a hit skips
    every paid API call entirely. On a fresh success, the result is cached
    for next time.
    """
    try:
        cached = None if force_regenerate else await _cache_lookup(url)
        if cached:
            await _apply_cached_result(session, cached)
            return

        if creative_direction:
            session.state["user_creative_direction"] = creative_direction
        await _run_strategist_phase(session, url)
        await _run_director_phase(session)
        await _run_post_production_phase(session)
        await _cache_save(session, url)
    except Exception as e:
        session.error = str(e)
        await session.emit("system", "error", f"Pipeline failed: {e}")
    finally:
        session.finished = True
        await session.event_queue.put(None)  # sentinel for SSE stream


async def resume_pipeline(session: Session) -> None:
    """Re-enter a failed run at the last successful stage.

    Each phase's output (brand_brief, asset_bundle, final_video_path) is
    already in session.state if it succeeded, so we skip straight to
    whichever phase actually failed instead of re-paying for scraping,
    briefing, and image/music/voice generation that already worked.
    """
    try:
        if "brand_brief" not in session.state:
            await _run_strategist_phase(session, session.state.get("source_url", ""))
        else:
            await session.emit("system", "message", "Resuming — brief already locked, skipping Strategist.")

        if "asset_bundle" not in session.state:
            await _run_director_phase(session)
        else:
            await session.emit("system", "message", "Resuming — assets already bundled, skipping Creative Director.")

        if "final_video_path" not in session.state:
            if "veo_clip_paths" in session.state:
                # Veo clips already generated — only the mux failed.
                # Skip the expensive Veo re-run and go straight to sync.
                await session.emit("system", "message", "Resuming — Veo clips already generated, skipping straight to sync.")
                await _remux_only(session)
                await session.emit(
                    "post_production", "done", "Final video ready",
                    final_video_path=session.state["final_video_path"],
                    duration_sec=session.state.get("final_duration"),
                    phase="post_production",
                )
            else:
                await _run_post_production_phase(session)
        else:
            await session.emit("system", "message", "Resuming — final video already produced.")

        await _cache_save(session, session.state.get("source_url", ""))
    except Exception as e:
        session.error = str(e)
        await session.emit("system", "error", f"Resume failed: {e}")
    finally:
        session.finished = True
        await session.event_queue.put(None)


async def select_hero_image(session: Session, candidate_index: int) -> None:
    """Manually override which already-generated candidate becomes the hero.

    Veo only takes one starting frame, so when the auto-ranker picks the
    wrong candidate (e.g. a generic shot over one with visible branding),
    this swaps in a candidate that's already on disk and re-runs only
    Post-Production — no re-scraping, re-briefing, or re-generating images.
    """
    try:
        ranked = session.state.get("ranked_images") or []
        match = next((r for r in ranked if r["candidate"]["index"] == candidate_index), None)
        if not match:
            raise RuntimeError(f"No candidate with index {candidate_index} in ranked_images")

        bundle = dict(session.state.get("asset_bundle") or {})
        bundle["hero_image_path"] = match["candidate"]["path"]
        bundle["image_ranking_reasoning"] = "Manually selected by user, overriding the automatic ranking."
        session.state["asset_bundle"] = bundle

        await session.emit(
            "creative_director", "message",
            f"Hero image manually overridden to candidate {candidate_index}",
            asset_bundle=bundle,
            phase="creative_director",
        )

        await _run_post_production_phase(session)
        await _cache_save(session, session.state.get("source_url", ""))
    except Exception as e:
        session.error = str(e)
        await session.emit("system", "error", f"Hero override failed: {e}")
    finally:
        session.finished = True
        await session.event_queue.put(None)


def _parse_critique(raw: Any) -> dict | None:
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


# ────────────────────────────────────────────────────────────────────────────
# Feedback handling — route via supervisor, re-run the targeted agent
# ────────────────────────────────────────────────────────────────────────────

async def handle_feedback(session: Session, feedback_text: str) -> None:
    """Route user feedback to the right agent and re-run that part of the pipeline."""
    try:
        await session.emit(
            "supervisor",
            "thinking",
            f"Classifying feedback: \"{feedback_text}\"",
        )
        state = await _run_agent(
            supervisor_agent,
            user_message=(
                f"User feedback on the finished video: \"{feedback_text}\"\n\n"
                f"Current brief: {json.dumps(session.state.get('brand_brief'), indent=2)[:1500]}\n\n"
                "Return your routing JSON."
            ),
            session=session,
            initial_state=session.state,
        )
        decision_raw = state.get("supervisor_decision", "")
        decision = _parse_critique(decision_raw) or {}
        target = decision.get("target_agent", "creative_director")
        instructions = decision.get("instructions_to_agent", feedback_text)

        await session.emit(
            "supervisor",
            "handoff",
            f"Routing to {target}: {decision.get('interpretation', feedback_text)}",
            decision=decision,
        )

        if target == "strategist":
            await session.emit("system", "handoff", "→ Brand Strategist taking over", phase="strategist")
            new_state = await _run_agent(
                strategist_agent,
                user_message=(
                    f"Revise the brief per this feedback: {instructions}\n"
                    "Use the existing brief in state as the starting point; do not re-scrape."
                ),
                session=session,
                initial_state=session.state,
            )
            session.state.update(new_state)
            await session.emit(
                "strategist", "message",
                f"Brief revised: {session.state['brand_brief']['business_name']}",
                brief=session.state.get("brand_brief"),
                phase="strategist",
            )
            # Cascade through director + post-production with the revised brief
            await _rerun_director_and_post(session)

        elif target == "creative_director":
            scope = set(decision.get("asset_scope") or [])
            if not scope:
                # Supervisor didn't (or couldn't) scope it. Safe fallback is
                # the full redo, not silently skipping an asset that needed
                # to change.
                await session.emit("system", "handoff", "→ Creative Director taking over", phase="creative_director")
                new_state = await _run_agent(
                    creative_director_agent,
                    user_message=f"Re-produce assets per this feedback: {instructions}",
                    session=session,
                    initial_state=session.state,
                )
                session.state.update(new_state)
                await session.emit(
                    "creative_director", "message", "Asset bundle regenerated",
                    asset_bundle=session.state.get("asset_bundle"),
                    phase="creative_director",
                )
                await _rerun_post_production(session)
            else:
                await _rerun_director_scoped(session, scope, instructions)

        elif target == "post_production":
            await session.emit("system", "handoff", "→ Post-Production taking over", phase="post_production")
            new_state = await _run_agent(
                post_production_agent,
                user_message=f"Re-render the final video per this feedback: {instructions}",
                session=session,
                initial_state=session.state,
            )
            session.state.update(new_state)

        await session.emit(
            "post_production",
            "done",
            "Revised video ready",
            final_video_path=session.state.get("final_video_path"),
            duration_sec=session.state.get("final_duration"),
            phase="post_production",
        )
        await _cache_save(session, session.state.get("source_url", ""))
    except Exception as e:
        session.error = str(e)
        await session.emit("system", "error", f"Feedback handling failed: {e}")
    finally:
        await session.event_queue.put(None)


async def _rerun_director_and_post(session: Session) -> None:
    await session.emit("system", "handoff", "→ Creative Director taking over", phase="creative_director")
    state = await _run_agent(
        creative_director_agent,
        user_message="The brief was revised. Re-produce assets accordingly.",
        session=session,
        initial_state=session.state,
    )
    session.state.update(state)
    await session.emit(
        "creative_director", "message", "Asset bundle regenerated",
        asset_bundle=session.state.get("asset_bundle"),
        phase="creative_director",
    )
    await _rerun_post_production(session)


async def _rerun_post_production(session: Session) -> None:
    await session.emit("system", "handoff", "→ Post-Production taking over", phase="post_production")
    state = await _run_agent(
        post_production_agent,
        user_message="Re-render the final video with the updated assets.",
        session=session,
        initial_state=session.state,
    )
    session.state.update(state)


# ────────────────────────────────────────────────────────────────────────────
# Scoped Director re-runs — regenerate only the asset(s) feedback concerns.
# "images" still needs an LLM (new prompts require creative interpretation of
# the feedback), but it's tool-restricted so it physically cannot touch
# music/voiceover. "music"/"voiceover" need no LLM at all — the existing
# brief already says what they should sound like, so we call Lyria/TTS
# directly with the feedback appended as a hint, skipping an agent call
# entirely.
# ────────────────────────────────────────────────────────────────────────────

async def _rerun_director_scoped(session: Session, scope: set[str], instructions: str) -> None:
    if "images" in scope:
        await session.emit(
            "system", "handoff", "→ Creative Director (images only) taking over",
            phase="creative_director",
        )
        new_state = await _run_agent(
            creative_director_images_agent,
            user_message=f"Feedback to address in the new image prompts: {instructions}",
            session=session,
            initial_state=session.state,
        )
        session.state.update(new_state)
        _sync_images_into_bundle(session)
        await session.emit(
            "creative_director", "message", "Images regenerated",
            asset_bundle=session.state["asset_bundle"],
            phase="creative_director",
        )

    if "music" in scope:
        await session.emit(
            "system", "handoff", "→ Creative Director (music only) taking over",
            phase="creative_director",
        )
        await _regenerate_music(session, instructions)

    if "voiceover" in scope:
        await session.emit(
            "system", "handoff", "→ Creative Director (voiceover only) taking over",
            phase="creative_director",
        )
        await _regenerate_voiceover(session, instructions)

    if "images" in scope:
        # The hero image actually changed — the video frames need to match.
        await _rerun_post_production(session)
    else:
        # Only audio changed — remux the existing footage instead of paying
        # for Veo again to regenerate video that doesn't need to change.
        await _remux_only(session)


def _sync_images_into_bundle(session: Session) -> None:
    """Mirror what `package_assets` does for the image fields only — the
    scoped images-only Director has no package_assets tool, so nothing else
    updates asset_bundle after it runs."""
    hero = session.state["hero_image"]
    bundle = dict(session.state["asset_bundle"])
    bundle["hero_image_path"] = hero["candidate"]["path"]
    bundle["image_ranking_reasoning"] = hero["reasoning"]
    bundle["all_candidates"] = session.state["image_candidates"]
    session.state["asset_bundle"] = bundle


async def _rewrite_audio_direction(original: str, instructions: str, kind: str) -> str:
    """Merge a feedback instruction into a music/voiceover direction as ONE
    coherent description, rather than naively concatenating old+new — e.g.
    old "driving acoustic guitar, brass stabs" + new "feature violin" both
    landing in the same prompt produces a contradictory mix, not a swap."""
    def _call() -> str:
        client = genai.Client()
        prompt = (
            f"Current {kind} direction: \"{original}\"\n\n"
            f"Requested change: \"{instructions}\"\n\n"
            f"Rewrite the {kind} direction as ONE coherent 1-2 sentence description "
            "that fully applies the requested change. If the change replaces an "
            "element (e.g. a different lead instrument or voice quality), remove "
            "the old one entirely instead of keeping both. Preserve any aspects "
            "of the original the request doesn't mention (tempo, mood, genre fit). "
            "Respond with ONLY the new description, no preamble, no quotes."
        )
        resp = client.models.generate_content(model=settings.MODEL_FAST, contents=[prompt])
        return (resp.text or "").strip()

    try:
        new_direction = await asyncio.to_thread(_call)
        return new_direction or instructions
    except Exception:
        # Best-effort rewrite — falling back to the raw instruction alone is
        # still better than the old bug (blending stale + new descriptions).
        return instructions


async def _regenerate_music(session: Session, instructions: str) -> None:
    brief = dict(session.state["brand_brief"])
    new_genre = await _rewrite_audio_direction(brief["audio"]["music_genre"], instructions, "music")
    music_path = await generate_music(new_genre, session_id=session.id)
    music_path = await cloud_cache.store_asset(music_path, session.id, "audio")

    brief["audio"] = {**brief["audio"], "music_genre": new_genre}
    session.state["brand_brief"] = brief

    bundle = dict(session.state["asset_bundle"])
    bundle["music_path"] = music_path
    bundle["music_prompt"] = new_genre
    session.state["asset_bundle"] = bundle

    await session.emit(
        "creative_director", "message", f"Music regenerated: {new_genre}",
        asset_bundle=bundle, phase="creative_director",
    )


async def _regenerate_voiceover(session: Session, instructions: str) -> None:
    brief = dict(session.state["brand_brief"])
    new_tone = await _rewrite_audio_direction(brief["audio"]["voiceover_tone"], instructions, "voiceover")
    voice_path, voice_dur = await generate_voiceover(
        script=brief["voiceover_script"],
        voice_name=brief["audio"]["voice_name"],
        tone_hint=new_tone,
        session_id=session.id,
    )
    voice_path = await cloud_cache.store_asset(voice_path, session.id, "audio")

    brief["audio"] = {**brief["audio"], "voiceover_tone": new_tone}
    session.state["brand_brief"] = brief

    bundle = dict(session.state["asset_bundle"])
    bundle["voiceover_path"] = voice_path
    bundle["voiceover_duration_sec"] = voice_dur
    session.state["asset_bundle"] = bundle

    await session.emit(
        "creative_director", "message", f"Voiceover regenerated: {new_tone}",
        asset_bundle=bundle, phase="creative_director",
    )


async def _remux_only(session: Session) -> None:
    """Re-mux the EXISTING Veo clips with the current music/voiceover —
    used when feedback only concerns audio, so we don't pay for Veo again
    to regenerate video frames that don't need to change. Falls back to a
    full Post-Production re-run if no clips survived (e.g. a session from
    before clips were kept instead of deleted after the first mux)."""
    clip_paths = session.state.get("veo_clip_paths")
    bundle = session.state.get("asset_bundle")
    if not clip_paths or not bundle:
        await _rerun_post_production(session)
        return

    await session.emit(
        "system", "handoff", "→ Post-Production (remux only — no Veo re-run) taking over",
        phase="post_production",
    )
    final_path, duration = await sync_video_audio(
        video_paths=clip_paths,
        music_path=bundle["music_path"],
        voiceover_path=bundle["voiceover_path"],
        session_id=session.id,
    )
    final_path = await cloud_cache.store_asset(final_path, session.id, "video")
    session.state["final_video_path"] = final_path
    session.state["final_duration"] = duration
