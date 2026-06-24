"""Shared helper for inspecting google-genai responses defensively.

Gemini/Lyria can return a 200 response with no usable content when a
generation gets safety/content-policy blocked — `candidates[0].content` is
`None` in that case, not an exception. Blind `.content.parts` access then
crashes with a confusing `AttributeError` instead of surfacing why.
"""
from __future__ import annotations

from typing import Any


def require_content_parts(resp: Any, label: str) -> list:
    """Return candidates[0].content.parts, or raise a clear error explaining
    why the generation was blocked instead of producing content."""
    candidates = getattr(resp, "candidates", None)
    if not candidates:
        raise RuntimeError(f"{label}: no candidates in response")

    candidate = candidates[0]
    if candidate.content is None:
        raise RuntimeError(
            f"{label}: blocked before producing content "
            f"(finish_reason={candidate.finish_reason}, {candidate.finish_message or ''})"
        )
    return candidate.content.parts
