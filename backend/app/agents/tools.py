"""ADK-compatible tool functions. Each is a Python callable an LlmAgent can invoke.

These are thin wrappers around the real generation tools in app.tools. They
exist because ADK tools must have JSON-serializable args and return values,
and because we want to update session state with structured data agents can
read in subsequent steps.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from google.adk.tools import ToolContext

from ..config import settings
from ..schemas import (
    AssetBundle,
    BrandBrief,
    FeedbackRoute,
    GeminiVoiceName,
    ImageCandidate,
    RankedImage,
)
from ..storage import cloud_cache
from ..tools import (
    generate_candidates,
    generate_music,
    generate_video_from_image,
    generate_voiceover,
    pick_winner,
    rank_images,
    scrape_site,
    sync_video_audio,
)


# ============================================================
# Strategist tools
# ============================================================

async def scrape_website(url: str, tool_context: ToolContext) -> dict[str, Any]:
    """Scrape a website and return a digest the agent can read.

    Args:
        url: The full URL of the website to scrape.
    """
    site = await scrape_site(url)
    tool_context.state["scraped_site"] = site.to_brain_input()
    tool_context.state["source_url"] = url
    return {
        "status": "ok",
        "digest": site.to_brain_input(),
        "page_count": len(site.pages),
        "image_count": len(site.image_urls),
        "css_colors": site.css_colors[:8],
        "fonts": site.fonts[:5],
    }


async def submit_brief(
    business_name: str,
    one_liner: str,
    target_audience: str,
    core_message: str,
    call_to_action: str,
    palette_primary: str,
    palette_secondary: str,
    palette_accent: str,
    palette_neutral: str,
    visual_aesthetic: str,
    visual_photography_style: str,
    visual_mood: list[str],
    visual_do_not: list[str],
    music_genre: str,
    voiceover_tone: str,
    voice_name: GeminiVoiceName,
    voiceover_script: str,
    tool_context: ToolContext,
    rebuttal: str = "",
) -> dict[str, Any]:
    """Submit the completed BrandBrief. Stores it in session state.

    Call this every round, even when you haven't changed anything in
    response to a critique.

    Args:
        rebuttal: Leave empty if you agree with the Critic's last critique
            (or there isn't one yet). If you disagree with some or all of
            the requested changes, explain specifically why here instead of
            making the change — the Critic will see this and either concede
            or respond with new reasoning. Don't push back reflexively; only
            use this when you have a substantive reason the brief is right
            as-is.
    """
    source_url = tool_context.state.get("source_url", "https://example.com")
    brief = BrandBrief(
        source_url=source_url,
        business_name=business_name,
        one_liner=one_liner,
        target_audience=target_audience,
        core_message=core_message,
        call_to_action=call_to_action,
        palette={
            "primary": palette_primary,
            "secondary": palette_secondary,
            "accent": palette_accent,
            "neutral": palette_neutral,
        },
        visual={
            "aesthetic": visual_aesthetic,
            "photography_style": visual_photography_style,
            "mood": visual_mood,
            "do_not": visual_do_not,
        },
        audio={
            "music_genre": music_genre,
            "voiceover_tone": voiceover_tone,
            "voice_name": voice_name,
        },
        voiceover_script=voiceover_script,
    )
    tool_context.state["brand_brief"] = brief.model_dump(mode="json")
    # Always overwrite, even with "" — a stale rebuttal from an earlier
    # round must not leak into the Critic's view of the current one.
    tool_context.state["strategist_rebuttal"] = rebuttal
    return {"status": "submitted", "business_name": business_name}


# ============================================================
# Creative Director tools
# ============================================================

async def generate_image_prompts(
    prompts: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Submit the diverse image prompts derived from the brief.

    Each prompt must be 40-80 words, describe a different composition/angle,
    and bake in the palette and aesthetic from the brief.

    Args:
        prompts: A list of detailed prompt strings, one per candidate image
            (see settings.IMAGE_CANDIDATES for the exact count expected).
    """
    if len(prompts) != settings.IMAGE_CANDIDATES:
        return {
            "status": "error",
            "message": f"Expected {settings.IMAGE_CANDIDATES} prompts, got {len(prompts)}",
        }
    tool_context.state["image_prompts"] = prompts
    return {"status": "ok", "prompt_count": len(prompts)}


async def generate_and_rank_images(tool_context: ToolContext) -> dict[str, Any]:
    """Generate images with Nano Banana Pro and rank them with Gemini.

    Reads `image_prompts` from state. Writes `image_candidates`, `ranked_images`,
    and `hero_image` to state.
    """
    prompts: list[str] = tool_context.state.get("image_prompts", [])
    if not prompts:
        return {"status": "error", "message": "No image_prompts in state"}

    session_id = tool_context.state["session_id"]
    candidates = await generate_candidates(prompts, session_id=session_id)
    if not candidates:
        return {"status": "error", "message": "Nano Banana returned no candidates"}

    brief_dict = tool_context.state["brand_brief"]
    brief_summary = (
        f"{brief_dict['business_name']} — {brief_dict['one_liner']}. "
        f"Aesthetic: {brief_dict['visual']['aesthetic']}. "
        f"Mood: {', '.join(brief_dict['visual']['mood'])}."
    )

    ranked = await rank_images(candidates, brief_summary=brief_summary)

    # Upload every candidate immediately (not just the winner — all of them
    # show up in the asset grid) so nothing the browser fetches depends on
    # this backend's local disk surviving past the current request. No-op,
    # local-path-preserving fallback if Supabase isn't configured.
    new_paths = await asyncio.gather(*[
        cloud_cache.store_asset(r.candidate.path, session_id, "images") for r in ranked
    ])
    ranked = [
        r.model_copy(update={"candidate": r.candidate.model_copy(update={"path": new_path})})
        for r, new_path in zip(ranked, new_paths)
    ]
    winner = pick_winner(ranked)

    tool_context.state["image_candidates"] = [r.candidate.model_dump() for r in ranked]
    tool_context.state["ranked_images"] = [r.model_dump() for r in ranked]
    tool_context.state["hero_image"] = winner.model_dump()

    return {
        "status": "ok",
        "candidate_count": len(candidates),
        "winner_index": winner.candidate.index,
        "winner_score": winner.score,
        "winner_reasoning": winner.reasoning,
    }


async def generate_music_and_voiceover(tool_context: ToolContext) -> dict[str, Any]:
    """Run Lyria 3 music gen and Gemini TTS voiceover in parallel."""
    brief_dict = tool_context.state["brand_brief"]
    session_id = tool_context.state["session_id"]

    music_task = generate_music(brief_dict["audio"]["music_genre"], session_id=session_id)
    voice_task = generate_voiceover(
        script=brief_dict["voiceover_script"],
        voice_name=brief_dict["audio"]["voice_name"],
        tone_hint=brief_dict["audio"]["voiceover_tone"],
        session_id=session_id,
    )
    music_path, (voice_path, voice_dur) = await asyncio.gather(music_task, voice_task)

    # Upload immediately — both get previewed in the asset grid and muxed
    # into the final video; neither should depend on local disk surviving
    # past this request.
    music_path, voice_path = await asyncio.gather(
        cloud_cache.store_asset(music_path, session_id, "audio"),
        cloud_cache.store_asset(voice_path, session_id, "audio"),
    )

    tool_context.state["music_path"] = music_path
    tool_context.state["voiceover_path"] = voice_path
    tool_context.state["voiceover_duration"] = voice_dur

    return {
        "status": "ok",
        "music_path": music_path,
        "voiceover_path": voice_path,
        "voiceover_duration_sec": round(voice_dur, 2),
    }


async def package_assets(tool_context: ToolContext) -> dict[str, Any]:
    """Bundle all Creative Director output for Post-Production."""
    brief_dict = tool_context.state["brand_brief"]
    hero = tool_context.state["hero_image"]
    bundle = AssetBundle(
        hero_image_path=hero["candidate"]["path"],
        image_ranking_reasoning=hero["reasoning"],
        all_candidates=[ImageCandidate(**c) for c in tool_context.state["image_candidates"]],
        music_path=tool_context.state["music_path"],
        music_prompt=brief_dict["audio"]["music_genre"],
        voiceover_path=tool_context.state["voiceover_path"],
        voiceover_script=brief_dict["voiceover_script"],
        voiceover_duration_sec=tool_context.state["voiceover_duration"],
    )
    tool_context.state["asset_bundle"] = bundle.model_dump()
    return {"status": "ok"}


# ============================================================
# Post-Production tools
# ============================================================

def _shot_image_paths(state: dict[str, Any]) -> list[str]:
    """Playback order for the final ad: hero image's shot first (the lead),
    then the other candidates in their original order — this is how every
    generated image ends up in the ad instead of the non-winners being
    thrown away."""
    bundle = state["asset_bundle"]
    hero_path = bundle["hero_image_path"]
    others = [c["path"] for c in bundle["all_candidates"] if c["path"] != hero_path]
    return [hero_path, *others]


async def generate_motion_prompts(
    motion_descriptions: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Submit one Veo motion description per shot, in playback order (hero
    image first, then the other candidates).

    Args:
        motion_descriptions: One motion description per shot. Each should be
            1-2 sentences describing subtle, cinematic camera and subject
            motion. Keep it gentle — Veo struggles with chaotic motion.
    """
    if len(motion_descriptions) != settings.IMAGE_CANDIDATES:
        return {
            "status": "error",
            "message": f"Expected {settings.IMAGE_CANDIDATES} motion descriptions, "
                       f"got {len(motion_descriptions)}",
        }
    tool_context.state["motion_prompts"] = motion_descriptions
    return {"status": "ok", "count": len(motion_descriptions)}


async def generate_veo_video(tool_context: ToolContext) -> dict[str, Any]:
    """Run Veo 3.1 image-to-video for every shot in parallel. Slow (60-180s)."""
    motion_prompts = tool_context.state["motion_prompts"]
    image_paths = _shot_image_paths(tool_context.state)
    session_id = tool_context.state["session_id"]

    clip_paths = await asyncio.gather(*[
        generate_video_from_image(
            image_path=image_path,
            motion_prompt=motion,
            session_id=session_id,
            shot_index=i,
        )
        for i, (image_path, motion) in enumerate(zip(image_paths, motion_prompts))
    ])
    tool_context.state["veo_clip_paths"] = list(clip_paths)
    return {"status": "ok", "clip_count": len(clip_paths), "clip_paths": list(clip_paths)}


async def sync_final_video(tool_context: ToolContext) -> dict[str, Any]:
    """Concatenate the Veo clips and mux with Lyria music + TTS voiceover."""
    bundle = tool_context.state["asset_bundle"]
    clip_paths = tool_context.state["veo_clip_paths"]
    session_id = tool_context.state["session_id"]

    # ffmpeg reads music_path/voiceover_path directly — they may already be
    # Supabase URLs at this point (uploaded immediately after generation),
    # and ffmpeg fetches http(s) inputs natively, so no local download step
    # is needed here.
    final_path, duration = await sync_video_audio(
        video_paths=clip_paths,
        music_path=bundle["music_path"],
        voiceover_path=bundle["voiceover_path"],
        session_id=session_id,
    )

    # Upload (don't delete) the raw clips — a later audio-only feedback round
    # (orchestrator._remux_only) reuses this exact footage instead of paying
    # for Veo again just to swap the music/voiceover track. This used to
    # delete them on the assumption "nothing reads them again", which broke
    # the moment scoped audio feedback needed to remux against them.
    clip_paths = await asyncio.gather(*[
        cloud_cache.store_asset(p, session_id, "video") for p in clip_paths
    ])
    tool_context.state["veo_clip_paths"] = list(clip_paths)

    # Upload the actual deliverable immediately — never required to survive
    # on this backend's local disk past this request.
    final_path = await cloud_cache.store_asset(final_path, session_id, "video")

    tool_context.state["final_video_path"] = final_path
    tool_context.state["final_duration"] = duration
    return {"status": "ok", "final_video_path": final_path, "duration_sec": round(duration, 2)}
