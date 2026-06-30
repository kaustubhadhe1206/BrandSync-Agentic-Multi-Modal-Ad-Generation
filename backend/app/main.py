"""BrandSync FastAPI app entry."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="BrandSync",
        version="1.0.0",
        description="Multi-agent AI system that turns websites into cinematic video ads.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import os
    import uvicorn
    # Local dev default stays port 8000 + reload; Render (and most PaaS)
    # inject PORT and the Dockerfile's own CMD runs uvicorn without --reload
    # directly, so this path mainly matters for `python -m app.main` locally.
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
