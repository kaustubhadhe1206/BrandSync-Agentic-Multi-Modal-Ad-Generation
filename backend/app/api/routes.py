"""FastAPI routes. SSE for live agent activity, REST for generate/feedback."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, HttpUrl

from ..config import settings
from ..storage import store
from .orchestrator import handle_feedback, resume_pipeline, run_full_pipeline, select_hero_image


router = APIRouter(prefix="/api")


class GenerateRequest(BaseModel):
    url: HttpUrl
    force_regenerate: bool = False


class GenerateResponse(BaseModel):
    session_id: str


class FeedbackRequestBody(BaseModel):
    feedback: str


class SelectHeroBody(BaseModel):
    candidate_index: int


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, background: BackgroundTasks) -> GenerateResponse:
    """Start a new generation job. Returns session_id immediately; progress streams via /events."""
    session = store.create()
    background.add_task(run_full_pipeline, session, str(req.url), req.force_regenerate)
    return GenerateResponse(session_id=session.id)


@router.post("/sessions/{session_id}/feedback")
async def submit_feedback(
    session_id: str,
    body: FeedbackRequestBody,
    background: BackgroundTasks,
) -> dict:
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Allow new event flow on the same session
    session.finished = False
    session.error = None
    background.add_task(handle_feedback, session, body.feedback)
    return {"status": "queued"}


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str, background: BackgroundTasks) -> dict:
    """Retry a failed run from its last successful stage instead of starting over."""
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.error:
        raise HTTPException(status_code=400, detail="Session has no error to resume from")

    session.finished = False
    session.error = None
    background.add_task(resume_pipeline, session)
    return {"status": "queued"}


@router.post("/sessions/{session_id}/select-hero")
async def select_hero(
    session_id: str,
    body: SelectHeroBody,
    background: BackgroundTasks,
) -> dict:
    """Override the auto-ranked hero image with a different already-generated
    candidate, then re-render only Post-Production (no re-scrape/re-brief/
    re-image-gen)."""
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.state.get("ranked_images"):
        raise HTTPException(status_code=400, detail="No ranked images available for this session")

    session.finished = False
    session.error = None
    background.add_task(select_hero_image, session, body.candidate_index)
    return {"status": "queued"}


@router.get("/sessions/{session_id}/events")
async def stream_events(session_id: str, request: Request) -> StreamingResponse:
    """SSE stream of all agent events for this session."""
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_gen():
        # Replay any events that already happened (in case the frontend connects late)
        for ev in list(session.events):
            yield _format_sse(ev)

        # Then stream new events as they arrive
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(session.event_queue.get(), timeout=30)
            except asyncio.TimeoutError:
                # Keep-alive comment
                yield ": keep-alive\n\n"
                continue
            if ev is None:  # sentinel
                yield "event: end\ndata: {}\n\n"
                break
            yield _format_sse(ev)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def _format_sse(ev) -> str:
    payload = {
        "timestamp": ev.timestamp,
        "agent": ev.agent,
        "kind": ev.kind,
        "text": ev.text,
        "data": ev.data,
    }
    return f"event: {ev.kind}\ndata: {json.dumps(payload)}\n\n"


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """Snapshot of session state — used by frontend for full state on connect."""
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "finished": session.finished,
        "error": session.error,
        "state": {
            "brand_brief": session.state.get("brand_brief"),
            "asset_bundle": session.state.get("asset_bundle"),
            "ranked_images": session.state.get("ranked_images"),
            "final_video_path": session.state.get("final_video_path"),
            "final_duration": session.state.get("final_duration"),
        },
    }


@router.get("/artifacts/{session_id}/{path:path}")
async def serve_artifact(session_id: str, path: str):
    """Serve any file from a session's artifact directory."""
    file_path = (settings.OUTPUT_DIR / session_id / path).resolve()
    base = settings.OUTPUT_DIR.resolve()
    # Path traversal guard
    if not str(file_path).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(file_path))
