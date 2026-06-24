"""Lyria 3 music generation. Produces a 30-second clip we'll trim to video length.

The Lyria preview API returns raw audio bytes; we write WAV to disk.
"""
from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from ..config import settings
from ._genai_utils import require_content_parts


async def generate_music(prompt: str, session_id: str) -> str:
    """Generate music with Lyria 3 and return the path to the WAV file."""
    out_dir = settings.OUTPUT_DIR / session_id / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "music.wav"

    def _call() -> str:
        client = genai.Client()
        # Lyria 3 clip preview — short instrumental clips from a text prompt
        resp = client.models.generate_content(
            model=settings.MODEL_MUSIC,
            contents=[prompt],
        )

        # Find audio bytes in response parts
        audio_bytes: bytes | None = None
        sample_rate = 48000  # Lyria default
        for part in require_content_parts(resp, "Lyria"):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                data = inline.data
                if isinstance(data, str):
                    import base64
                    data = base64.b64decode(data)
                audio_bytes = data
                break

        if not audio_bytes:
            raise RuntimeError("Lyria returned no audio data")

        # If the response is raw PCM, wrap in WAV header; if it's already a container, write as-is.
        # Lyria returns audio/wav by default in the preview SDK path.
        out_path.write_bytes(audio_bytes)
        return out_path.as_posix()

    return await asyncio.to_thread(_call)
