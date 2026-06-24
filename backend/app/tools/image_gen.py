"""Nano Banana Pro image generation. Real Gemini API calls, no mocks."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from google import genai

from ..config import settings
from ..schemas import ImageCandidate
from ._genai_utils import require_content_parts


def _client() -> genai.Client:
    # google-genai reads GEMINI_API_KEY from env; settings.ensure_dirs() sets it
    return genai.Client()


async def generate_candidates(
    prompts: list[str],
    session_id: str,
) -> list[ImageCandidate]:
    """Run N image generations in parallel and write PNGs to disk.

    Each prompt produces one image. The Creative Director typically requests
    4 diverse prompts so the ranker has real choices to compare.
    """
    out_dir = settings.OUTPUT_DIR / session_id / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    async def _one(idx: int, prompt: str) -> ImageCandidate | None:
        # The genai SDK is sync; offload to a worker thread
        def _call() -> ImageCandidate | None:
            client = _client()
            resp = client.models.generate_content(
                model=settings.MODEL_IMAGE,
                contents=[prompt],
            )
            try:
                parts = require_content_parts(resp, "Nano Banana")
            except RuntimeError:
                # One blocked candidate shouldn't sink the whole batch — the
                # other prompt(s) may still produce a usable image.
                return None
            for part in parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    fname = out_dir / f"cand_{idx}_{uuid.uuid4().hex[:6]}.png"
                    # Try the convenience method first, fall back to raw bytes
                    try:
                        img = part.as_image()
                        img.save(str(fname))
                    except Exception:
                        data = part.inline_data.data
                        if isinstance(data, str):
                            import base64
                            data = base64.b64decode(data)
                        fname.write_bytes(data)
                    return ImageCandidate(index=idx, path=fname.as_posix(), prompt=prompt)
            return None

        return await asyncio.to_thread(_call)

    results = await asyncio.gather(*[_one(i, p) for i, p in enumerate(prompts)])
    return [r for r in results if r is not None]
