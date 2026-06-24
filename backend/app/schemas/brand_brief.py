"""BrandBrief — the StyleContract the Strategist hands to the Creative Director.

This is the single most important data structure in the system. It's the
contract between agents: the Strategist owns producing it, the Director
owns executing against it, and the user's feedback edits it.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, HttpUrl

# Gemini TTS prebuilt voice names. The Strategist must pick one of these —
# free-text voice names (e.g. "Friendly Announcer") 404 against the TTS API.
GeminiVoiceName = Literal["Kore", "Puck", "Charon", "Leda", "Zephyr", "Fenrir", "Aoede", "Orus"]


class ColorPalette(BaseModel):
    primary: str = Field(description="Primary brand hex color, e.g. #C2410C")
    secondary: str = Field(description="Secondary hex color")
    accent: str = Field(description="Accent hex color used sparingly")
    neutral: str = Field(description="Neutral background hex color")


class VisualStyle(BaseModel):
    aesthetic: str = Field(
        description="One-line aesthetic descriptor, e.g. 'warm artisanal pizzeria, "
                    "candlelight, hand-thrown ceramics'"
    )
    photography_style: str = Field(
        description="Style of imagery: 'editorial food photography' / 'cinematic "
                    "wide shots' / 'minimalist product shots on solid background'"
    )
    mood: list[str] = Field(
        description="3-5 mood adjectives, e.g. ['cozy', 'authentic', 'inviting']"
    )
    do_not: list[str] = Field(
        default_factory=list,
        description="Things to explicitly avoid: 'no cartoon style', 'no stock-photo "
                    "people', 'no neon'"
    )


class AudioDirection(BaseModel):
    music_genre: str = Field(
        description="Lyria prompt-friendly genre/mood, e.g. 'warm acoustic guitar, "
                    "soft jazz brushes, intimate cafe atmosphere'"
    )
    voiceover_tone: str = Field(
        description="Voiceover delivery, e.g. 'warm, confident, conversational male "
                    "narrator with slight Italian-American inflection'"
    )
    voice_name: GeminiVoiceName = Field(
        default="Kore",
        description="Gemini TTS prebuilt voice name"
    )


class BrandBrief(BaseModel):
    """The complete creative brief produced by the Strategist Agent."""

    source_url: HttpUrl
    business_name: str
    one_liner: str = Field(description="What the business is, in one sentence")
    target_audience: str
    core_message: str = Field(
        description="The single most important thing the ad should communicate"
    )
    call_to_action: str = Field(
        description="What the viewer should do after watching, e.g. 'Order online' "
                    "or 'Visit our SoHo location'"
    )

    palette: ColorPalette
    visual: VisualStyle
    audio: AudioDirection

    voiceover_script: str = Field(
        description="The full voiceover copy, ~12-15 words — Veo's hard cap is 8 "
                    "seconds and TTS runs ~2.2 words/sec, so anything longer gets cut off"
    )

    # Critique loop fields — set when Director rejects the brief
    critique_round: int = 0
    last_critique: str | None = None


class CritiqueFromDirector(BaseModel):
    """What the Creative Director sends back when rejecting a brief as unworkable."""
    accept: bool
    reason: str = Field(description="If rejecting, what specifically is missing or wrong")
    requested_changes: list[str] = Field(default_factory=list)
