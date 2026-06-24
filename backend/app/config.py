"""Central config. All model IDs and runtime settings live here."""
from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- API keys ---
    GOOGLE_API_KEY: str = ""  # AI Studio key; google-genai also reads GEMINI_API_KEY

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

    # --- Generation knobs ---
    IMAGE_CANDIDATES: int = 2          # how many images Nano Banana produces before ranking
    VIDEO_DURATION_SEC: int = 8        # Veo clip length
    SCRAPER_MAX_PAGES: int = 6
    SCRAPER_TIMEOUT_SEC: int = 15
    MAX_CRITIQUE_ITERATIONS: int = 2   # Strategist <-> Director loop guard

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
        # Propagate API key for google-genai SDK which reads env vars at client init
        if self.GOOGLE_API_KEY and not os.environ.get("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = self.GOOGLE_API_KEY


settings = Settings()
settings.ensure_dirs()
