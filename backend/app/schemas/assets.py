"""Asset schemas — what flows from Creative Director to Post-Production."""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field


class ImageCandidate(BaseModel):
    """A single image produced by Nano Banana, before ranking."""
    index: int
    path: str  # filesystem path to the PNG
    prompt: str


class RankedImage(BaseModel):
    """A ranked image with reasoning from the visual ranker."""
    candidate: ImageCandidate
    score: float = Field(ge=0.0, le=10.0)
    reasoning: str


class AssetBundle(BaseModel):
    """Everything the Creative Director produces, ready for Post-Production."""
    hero_image_path: str
    image_ranking_reasoning: str
    all_candidates: list[ImageCandidate]

    music_path: str
    music_prompt: str

    voiceover_path: str
    voiceover_script: str
    voiceover_duration_sec: float


class VideoSpec(BaseModel):
    """Final video output spec from Post-Production."""
    video_path: str
    duration_sec: float
    width: int = 1280
    height: int = 720


class FeedbackRequest(BaseModel):
    """User feedback after seeing the video."""
    session_id: str
    feedback_text: str


class FeedbackRoute(BaseModel):
    """Where the supervisor routes a feedback request."""
    target_agent: str  # 'strategist' | 'creative_director' | 'post_production'
    interpretation: str
    instructions_to_agent: str
    # Only meaningful when target_agent == 'creative_director'. Subset of
    # 'images' | 'music' | 'voiceover' — lets the Director regenerate only
    # what the feedback actually concerns instead of redoing every asset.
    asset_scope: list[str] = Field(default_factory=list)
