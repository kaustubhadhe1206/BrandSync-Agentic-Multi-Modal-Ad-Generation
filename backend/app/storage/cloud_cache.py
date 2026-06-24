"""Optional Supabase-backed cache for completed generations.

Generating a video costs real money (Veo + Lyria + 4x image gen). If someone
requests the same business URL again, there's no reason to re-pay for it —
this looks up a cached result first and only falls through to a real
pipeline run on a miss. Storage lives in Supabase (DB row + Storage bucket),
not local disk, so it survives restarts/redeploys.

Disabled automatically when SUPABASE_URL/SUPABASE_KEY aren't set in .env —
every method becomes a no-op and the app behaves exactly as if this module
didn't exist.
"""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from ..config import settings

_TABLE = "cached_generations"


def _normalize_url(url: str) -> str:
    """Collapse tracking params / www / trailing slashes so the same
    business isn't cached under a dozen near-duplicate URLs."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme or "https", netloc, path, "", "", ""))


def _cache_key(url: str) -> str:
    return hashlib.sha256(_normalize_url(url).encode()).hexdigest()[:24]


class CloudCache:
    def __init__(self) -> None:
        # create_client() just builds a client object — no network I/O — so
        # this is safe to run at import time. Bucket creation is NOT: it's a
        # real network call, deferred to first actual get()/put() (and
        # wrapped in the same timeout) so a slow/unreachable Supabase can
        # never hang the whole app at startup, which is what a synchronous
        # call here used to risk for an optional, best-effort feature.
        self._client = None
        self._bucket_ready = False
        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            try:
                from supabase import create_client

                self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            except Exception:
                self._client = None

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            from storage3.types import CreateOrUpdateBucketOptions

            self._client.storage.create_bucket(
                settings.SUPABASE_BUCKET,
                options=CreateOrUpdateBucketOptions(public=True),
            )
        except Exception:
            pass  # bucket already exists (or it genuinely failed — the
            # upload right after this call will surface that instead)
        self._bucket_ready = True

    async def store_asset(self, local_path: str | None, session_id: str, category: str) -> str | None:
        """Upload a freshly-written local file to Storage and return its
        public URL, deleting the local copy afterward — so nothing the
        browser fetches ever depends on this backend's local disk surviving
        past the current request (ephemeral on most hosts, and useless
        across instances if this ever scales beyond one).

        Best-effort: on any failure, falls back to the local path rather
        than failing the generation outright — and that's also exactly the
        behavior when Supabase isn't configured at all, so local dev without
        credentials keeps working unchanged.
        """
        if not local_path or not self.is_configured:
            return local_path
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._store_asset_sync, local_path, session_id, category),
                timeout=60,
            )
        except Exception:
            return local_path

    def _store_asset_sync(self, local_path: str, session_id: str, category: str) -> str:
        self._ensure_bucket()
        local_file = Path(local_path)
        if not local_file.is_file():
            return local_path
        remote_path = f"{session_id}/{category}/{local_file.name}"
        mime, _ = mimetypes.guess_type(local_file.name)
        bucket = self._client.storage.from_(settings.SUPABASE_BUCKET)
        bucket.upload(
            remote_path,
            local_file.read_bytes(),
            {"content-type": mime or "application/octet-stream", "upsert": "true"},
        )
        public_url = bucket.get_public_url(remote_path)
        try:
            local_file.unlink()
        except OSError:
            pass
        return public_url

    async def get(self, url: str) -> dict[str, Any] | None:
        if not self.is_configured:
            return None
        return await asyncio.wait_for(asyncio.to_thread(self._get_sync, url), timeout=10)

    def _get_sync(self, url: str) -> dict[str, Any] | None:
        # No bucket needed for a metadata lookup — only put() uploads files.
        res = (
            self._client.table(_TABLE)
            .select("brand_brief,asset_bundle,ranked_images,final_video_path,final_duration")
            .eq("url", _normalize_url(url))
            .maybe_single()
            .execute()
        )
        return res.data if res and res.data else None

    async def put(self, url: str, session_id: str, state: dict[str, Any]) -> None:
        """Upload this run's artifact files to Storage and upsert the brief/
        asset metadata with cloud URLs swapped in for local disk paths."""
        if not self.is_configured:
            return
        await asyncio.wait_for(
            asyncio.to_thread(self._put_sync, url, session_id, state), timeout=60
        )

    def _put_sync(self, url: str, session_id: str, state: dict[str, Any]) -> None:
        self._ensure_bucket()
        key = _cache_key(url)
        local_root = settings.OUTPUT_DIR / session_id
        uploaded: dict[str, str] = {}

        def upload(local_path: str | None) -> str | None:
            if not local_path:
                return local_path
            if local_path in uploaded:
                return uploaded[local_path]
            local_file = Path(local_path)
            if not local_file.is_file():
                return local_path
            try:
                rel = local_file.relative_to(local_root).as_posix()
            except ValueError:
                rel = local_file.name
            remote_path = f"{key}/{rel}"
            mime, _ = mimetypes.guess_type(local_file.name)
            bucket = self._client.storage.from_(settings.SUPABASE_BUCKET)
            bucket.upload(
                remote_path,
                local_file.read_bytes(),
                {"content-type": mime or "application/octet-stream", "upsert": "true"},
            )
            public_url = bucket.get_public_url(remote_path)
            uploaded[local_path] = public_url
            return public_url

        bundle = dict(state["asset_bundle"]) if state.get("asset_bundle") else None
        if bundle:
            bundle["hero_image_path"] = upload(bundle.get("hero_image_path"))
            bundle["music_path"] = upload(bundle.get("music_path"))
            bundle["voiceover_path"] = upload(bundle.get("voiceover_path"))
            bundle["all_candidates"] = [
                {**c, "path": upload(c.get("path"))} for c in bundle.get("all_candidates", [])
            ]

        ranked = [
            {**r, "candidate": {**r["candidate"], "path": upload(r["candidate"].get("path"))}}
            for r in (state.get("ranked_images") or [])
        ]

        cached = {
            "url": _normalize_url(url),
            "brand_brief": state.get("brand_brief"),
            "asset_bundle": bundle,
            "ranked_images": ranked or None,
            "final_video_path": upload(state.get("final_video_path")),
            "final_duration": state.get("final_duration"),
        }
        self._client.table(_TABLE).upsert(cached, on_conflict="url").execute()


cloud_cache = CloudCache()
