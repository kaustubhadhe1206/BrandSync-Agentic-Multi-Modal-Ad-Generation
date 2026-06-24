# BrandSync

> A multi-agent AI system that turns a website URL into a cinematic 8-second video ad.

Three Google ADK agents collaborate to produce the final cut:

```
    ┌──────────────┐  brief + critique  ┌──────────────────┐
URL ─►│  Strategist  │◄──────────────────►│ Creative Director │
    └──────────────┘                    └────────┬─────────┘
            ▲                                     │ asset bundle
            │ user feedback                       ▼
            │ routed by Supervisor       ┌──────────────────┐
            └────────────────────────────│ Post-Production   │──► final.mp4
                                          └──────────────────┘
```

This is genuinely multi-agent, not just a renamed pipeline:

- **Strategist ↔ Critic loop**: the Critic agent rejects vague briefs and forces revisions (up to N rounds) before the Director ever sees the brief. This catches "modern feel" briefs before they cost a Veo call.
- **Supervisor routes feedback**: "make the music jazzier" goes to the Director, "lead with the family-owned story" goes back to the Strategist, "voiceover is too quiet" goes to Post-Production. Each path re-runs only the necessary subgraph.
- **Real critique state**: every handoff carries structured Pydantic data (`BrandBrief`, `AssetBundle`, `VideoSpec`) so failures are localized and resumable.

## Stack

| Layer | Tech |
| --- | --- |
| Agents | Google ADK (`google-adk`) |
| LLMs | Gemini 3 Pro Preview (reasoning) · Gemini 3.1 Flash (routing/ranking) |
| Image gen | Nano Banana Pro (`gemini-3-pro-image-preview`) |
| Image ranking | Gemini 3.1 Flash multimodal |
| Video gen | Veo 3.1 (`veo-3.1-generate-preview`) |
| Music | Lyria 3 (`lyria-3-clip-preview`) |
| TTS | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) |
| Sync/mux | FFmpeg subprocess |
| Backend | FastAPI + SSE |
| Frontend | React 18 + Vite + Tailwind + React Router |

## Setup

### Prereqs

- Python 3.11+
- Node 18+
- `ffmpeg` and `ffprobe` on PATH (`brew install ffmpeg` / `apt install ffmpeg`)
- Google AI Studio API key with access to the preview models above ([get one](https://aistudio.google.com/app/apikey))

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# put your AI Studio key in .env
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`. The Vite proxy forwards `/api/*` to the backend.

## How it works

### 1. Strategist + Critic loop

The Strategist scrapes the site (real BS4 + httpx, captures copy + CSS colors + fonts + image URLs) and writes a `BrandBrief`. The Critic — a separate `LlmAgent` running inside an ADK `LoopAgent` — evaluates whether the brief is concrete enough to execute. If not, it returns structured JSON requesting specific changes and the loop runs again, up to `MAX_CRITIQUE_ITERATIONS`.

### 2. Creative Director

Reads the approved brief, generates 4 diverse image prompts, calls Nano Banana Pro in parallel for all 4, then uses a separate Gemini Flash multimodal call to rank them (sends all 4 images + the brief summary, asks for JSON scores). The winner becomes the hero. Music (Lyria) and voiceover (Gemini TTS) run concurrently with the image rendering where possible.

### 3. Post-Production

Writes a Veo motion prompt for the hero image, calls Veo 3.1 (long-running operation, polled), then mixes the result with the music and voiceover using FFmpeg — voiceover at full volume, music ducked 14 dB so the VO sits clearly on top.

### 4. Feedback loop

When the user sends a note like *"change the music to jazz"*, the Supervisor (a separate `LlmAgent` on Gemini Flash) classifies which agent owns that change and re-runs only the necessary downstream graph. A music change skips re-scraping and re-briefing — it goes straight to the Director.

## What's real (no mocks)

- ✅ Web scraping is real BS4 + httpx with CSS theme extraction
- ✅ Nano Banana Pro real API calls, real PNGs written to disk
- ✅ Image ranker really sends images to Gemini multimodal
- ✅ Lyria really called — real WAV produced
- ✅ Gemini TTS really called — real WAV with prosody
- ✅ Veo really called — async polled to completion
- ✅ FFmpeg real subprocess for muxing
- ✅ ADK `Runner` orchestrates real agent loops; the LLM decides when to call tools

## Project layout

```
brandsync/
├── backend/
│   ├── app/
│   │   ├── agents/         # ADK agents: strategist, critic, director, post, supervisor
│   │   ├── tools/          # real implementations: scraper, Nano Banana, Lyria, TTS, Veo, FFmpeg
│   │   ├── schemas/        # Pydantic contracts between agents
│   │   ├── api/            # FastAPI routes + SSE orchestrator
│   │   ├── storage/        # in-memory session store + Supabase cloud_cache
│   │   │                   # (every generated asset uploads immediately,
│   │   │                   # local disk is scratch-only)
│   │   ├── config.py       # model IDs and settings
│   │   └── main.py
│   └── requirements.txt
└── frontend/
    └── src/
        ├── pages/          # Home, Generation
        ├── components/     # AgentColumn, BriefCard, AssetGrid, VideoPlayer
        ├── api/client.js   # fetch + SSE
        └── styles/
```

## Cost note

Veo and Lyria preview tiers are not free. A single end-to-end run costs a few US dollars at current Vertex/AI Studio rates. Don't leave the feedback loop running in a tab.

## Roadmap

- Persist session metadata (state, event history) to Redis/sqlite — it's still in-memory-only, so a restart or running more than one instance loses/can't-see active sessions, even though the generated assets themselves are already Supabase-backed and survive fine
- Multi-shot videos (Veo → frame extraction → Veo again for a second clip)
- A2A protocol so the agents could be deployed as independent services
