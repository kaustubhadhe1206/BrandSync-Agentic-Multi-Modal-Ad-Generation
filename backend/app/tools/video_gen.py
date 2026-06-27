"""Veo 3.1 video generation. Image-to-video, async long-running operation.

Veo is the slowest step (60-180s typical). We poll the operation handle
until done, then download the MP4.
"""
from __future__ import annotations

import asyncio
import mimetypes
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import types as genai_types

from ..config import settings

_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = (20, 40)  # wait before attempt 2, then before attempt 3


class VeoSafetyBlocked(RuntimeError):
    """Raised when Veo completes but withholds the video for responsible-AI
    reasons. Not transient — retrying the same image+prompt will fail the
    same way, so this is deliberately NOT caught by the retry loop below."""


def _load_image(image_path: str) -> genai_types.Image:
    """Load a hero image for Veo, whether it's a local artifact path or a
    remote URL (cached results point at Supabase Storage). `Image.from_file`
    only understands local disk and `storage.googleapis.com`/`gs://` — any
    other URL falls through to its local-path branch and crashes trying to
    open an https:// string as a file. So for any other http(s) URL, fetch
    the bytes ourselves and build the Image directly from them."""
    if image_path.startswith("http://") or image_path.startswith("https://"):
        resp = httpx.get(image_path, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        mime_type = resp.headers.get("content-type") or mimetypes.guess_type(image_path)[0]
        return genai_types.Image(image_bytes=resp.content, mime_type=mime_type)
    return genai_types.Image.from_file(location=image_path)


async def generate_video_from_image(
    image_path: str,
    motion_prompt: str,
    session_id: str,
    shot_index: int = 0,
) -> str:
    """Image-to-video with Veo. Returns the MP4 path.

    shot_index distinguishes multiple clips rendered for the same session
    (one per candidate image) so concurrent calls don't overwrite each
    other's output file.
    """
    out_dir = settings.OUTPUT_DIR / session_id / "video"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"veo_raw_{shot_index}.mp4"

    def _call() -> str:
        client = genai.Client()
        image = _load_image(image_path)

        operation = client.models.generate_videos(
            model=settings.MODEL_VIDEO,
            prompt=motion_prompt,
            image=image,
            config=genai_types.GenerateVideosConfig(
                number_of_videos=1,
                duration_seconds=settings.VIDEO_DURATION_SEC,
            ),
        )

        # Poll the long-running operation. Veo typically completes in 60-180s.
        timeout_at = time.time() + 600  # 10 min hard ceiling
        while not operation.done:
            if time.time() > timeout_at:
                raise TimeoutError("Veo generation exceeded 10-minute timeout")
            time.sleep(15)
            operation = client.operations.get(operation)

        if operation.error:
            raise RuntimeError(f"Veo operation failed: {operation.error.get('message', operation.error)}")

        response = operation.response
        if not response or not response.generated_videos:
            reasons = response.rai_media_filtered_reasons if response else None
            raise VeoSafetyBlocked(
                "Veo completed but returned no video — likely blocked by responsible-AI "
                f"safety filtering. reasons={reasons or 'unknown'}"
            )

        video = response.generated_videos[0].video
        # The Gemini Developer API returns a remote `uri` reference rather than
        # inline bytes for Veo; download() fetches the bytes and populates
        # video.video_bytes in place before we can save it.
        if not video.video_bytes:
            client.files.download(file=video)
        out_path.write_bytes(video.video_bytes)
        return out_path.as_posix()

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await asyncio.to_thread(_call)
        except VeoSafetyBlocked:
            # Deterministic content-policy block — the same image+prompt will
            # fail identically on retry, so don't waste another paid attempt.
            raise
        except (RuntimeError, TimeoutError) as e:
            last_error = e
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SEC[attempt])
    assert last_error is not None
    raise last_error
