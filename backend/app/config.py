"""Central config. All model IDs and runtime settings live here."""
from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- API keys ---
    GOOGLE_API_KEY: str = ""     # AI Studio key; google-genai also reads GEMINI_API_KEY
    ANTHROPIC_API_KEY: str = ""  # Claude — Strategist/Critic negotiation only

    # --- Cloud cache (optional) ---
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""  # service_role key (needs write access to DB + Storage)
    SUPABASE_BUCKET: str = "brandsync-cache"

    # --- Model IDs (verified June 2026) ---
    MODEL_BRAIN: str = "gemini-3.1-pro-preview"         # heavy reasoning / brief writing
    MODEL_FAST: str = "gemini-3.5-flash"                # routing, ranking, classification
    MODEL_IMAGE: str = "gemini-3-pro-image-preview"     # Nano Banana Pro
    MODEL_VIDEO: str = "veo-3.1-lite-generate-preview"  # Veo 3.1 Lite: $0.05/s @720p vs $0.40/s standard
    MODEL_MUSIC: str = "lyria-3-clip-preview"           # Lyria 3, 30s clip
    MODEL_TTS: str = "gemini-3.1-flash-tts-preview"
    MODEL_CRITIQUE: str = "claude-sonnet-4-6"           # Strategist + Critic negotiation

    # --- Generation knobs ---
    IMAGE_CANDIDATES: int = 2          # how many images Nano Banana produces before ranking
    VIDEO_DURATION_SEC: int = 8        # Veo clip length
    SCRAPER_MAX_PAGES: int = 6
    SCRAPER_TIMEOUT_SEC: int = 15
    SCRAPER_MAX_IMAGES_TO_ANALYZE: int = 5  # real images downloaded + described per scrape
    MAX_CRITIQUE_ITERATIONS: int = 4   # negotiation round cap (escalate gate usually exits earlier)

    # --- Deployment ---
    # Comma-separated list of origins allowed to call this API. Defaults to
    # the local Vite dev server; production deploys must set this to the
    # actual deployed frontend origin(s) (e.g. https://brandsync.vercel.app).
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # --- Filesystem ---
    OUTPUT_DIR: Path = Path("./artifacts")
    # Plain command names rely on PATH; override with an absolute path if
    # ffmpeg/ffprobe were just installed and PATH hasn't propagated yet
    # (common on Windows — a new terminal isn't always enough, the parent
    # shell/IDE process needs to restart too).
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    def ensure_dirs(self) -> None:
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # Propagate API keys for SDKs that read env vars directly at client
        # init (pydantic-settings loads .env into this object, not os.environ)
        if self.GOOGLE_API_KEY and not os.environ.get("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = self.GOOGLE_API_KEY
        if self.ANTHROPIC_API_KEY and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = self.ANTHROPIC_API_KEY


settings = Settings()
settings.ensure_dirs()
