"""Gemini TTS voiceover. Produces a WAV file with prosody control."""
from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from ..config import settings
from ._genai_utils import require_content_parts


def _write_wav(path: Path, pcm: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


async def generate_voiceover(
    script: str,
    voice_name: str,
    tone_hint: str,
    session_id: str,
) -> tuple[str, float]:
    """Generate voiceover audio. Returns (wav_path, duration_seconds)."""
    out_dir = settings.OUTPUT_DIR / session_id / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "voiceover.wav"

    # Prepend a style instruction; Gemini TTS responds to natural-language prosody hints
    styled_input = f"Say the following in a {tone_hint}: {script}"

    def _call() -> tuple[str, float]:
        client = genai.Client()
        resp = client.models.generate_content(
            model=settings.MODEL_TTS,
            contents=styled_input,
            config=genai_types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=genai_types.SpeechConfig(
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    )
                ),
            ),
        )

        pcm: bytes | None = None
        for part in require_content_parts(resp, "Gemini TTS"):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                data = inline.data
                if isinstance(data, str):
                    import base64
                    data = base64.b64decode(data)
                pcm = data
                break
        if not pcm:
            raise RuntimeError("Gemini TTS returned no audio")

        # Gemini TTS returns raw PCM 16-bit 24kHz mono
        _write_wav(out_path, pcm, channels=1, rate=24000, sample_width=2)

        # Compute duration from PCM length
        duration = len(pcm) / (24000 * 2)  # bytes / (rate * sample_width)
        return out_path.as_posix(), duration

    return await asyncio.to_thread(_call)
