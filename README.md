# BrandSync

> A multi-agent AI system that turns a website URL into a cinematic video ad.

```
URL ──► Strategist ◄──critique/rebuttal──► Critic   (LoopAgent, up to 4 rounds)
              │
              │ approved BrandBrief
              ▼
        Creative Director
              │ images · music · voiceover
              ▼
        Post-Production ──► final.mp4

User feedback → Supervisor classifies → routes to the exact responsible agent
```

This is genuinely multi-agent, not a renamed pipeline:

- **Strategist ↔ Critic negotiation**: the Critic rejects weak briefs and requests specific changes. The Strategist can comply *or push back with a reasoned rebuttal* — the Critic must then concede or counter with new reasoning, not just repeat itself. The loop exits the moment they reach consensus (`accept: true`), up to a 4-round cap as a cost safety valve.
- **Scoped feedback routing**: "change the music to violin" regenerates only the audio and remuxes using existing video footage — no Veo re-run. "I want people in the video" regenerates images and video. "The voiceover is too quiet" goes straight to Post-Production. Each path re-runs only what actually changed.
- **Real structured handoffs**: every inter-agent transfer carries validated Pydantic data (`BrandBrief`, `AssetBundle`) so failures are localized and the pipeline is resumable from the last successful stage.

## Stack

| Layer | Tech |
| --- | --- |
| Agents | Google ADK (`google-adk`) — `LlmAgent`, `LoopAgent`, custom `BaseAgent` |
| LLMs | Gemini 3.1 Pro Preview (Director/Post-Production) · Gemini 3.5 Flash (Supervisor, ranking, rewrite tasks) · **Claude Sonnet 4.6** (Strategist + Critic negotiation) |
| Image gen | Nano Banana Pro (`gemini-3-pro-image-preview`) |
| Image ranking | Gemini 3.5 Flash multimodal |
| Video gen | Veo 3.1 Lite (`veo-3.1-lite-generate-preview`) |
| Music | Lyria 3 (`lyria-3-clip-preview`) |
| TTS | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) |
| Sync/mux | FFmpeg subprocess |
| Backend | FastAPI + SSE |
| Frontend | React 18 + Vite + Tailwind + React Router |
| Storage | Supabase Storage (all generated assets) + Postgres (`cached_generations`, `sessions`) |

## Setup

### Prerequisites

- Python 3.11+
- Node 18+
- `ffmpeg` / `ffprobe` on PATH — `brew install ffmpeg` / `apt install ffmpeg` / `winget install ffmpeg`
- Google AI Studio API key ([get one](https://aistudio.google.com/app/apikey))
- Anthropic API key ([get one](https://console.anthropic.com/settings/keys)) — used only for the Strategist ↔ Critic negotiation loop
- Supabase project (free tier) with Storage enabled — for artifact storage and session persistence

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Fill in GOOGLE_API_KEY, ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY in .env
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`.

### Supabase tables

Run these once in your Supabase project's SQL Editor:

```sql
create table if not exists cached_generations (
  url text primary key,
  brand_brief jsonb,
  asset_bundle jsonb,
  ranked_images jsonb,
  final_video_path text,
  final_duration double precision
);

create table if not exists sessions (
  id text primary key,
  created_at double precision not null,
  state jsonb not null default '{}',
  events jsonb not null default '[]',
  finished boolean not null default false,
  error text
);
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`. The Vite proxy forwards `/api/*` to the backend.

## How it works

### 1. Strategist + Critic negotiation loop

The Strategist scrapes the site using real BS4 + httpx — it extracts page copy, CSS hex colors and fonts, and also downloads a handful of the site's actual images and runs a Gemini Flash multimodal call to describe any current promotions or seasonal campaigns visible in them. This catches visual-only context (a banner ad, a movie tie-in campaign) that page copy alone would miss.

From this it writes a `BrandBrief`. The Critic — a separate `LlmAgent` inside an ADK `LoopAgent` — evaluates it against four hard criteria: visual style specific enough to brief a photographer, voiceover script within the computed word-count range for the actual video duration, music genre with both genre and mood, and real hex palette values.

If rejected, the Strategist can revise *or push back*. A `rebuttal` argument on `submit_brief` lets the Strategist defend a contested choice with explicit reasoning; the Critic sees this next round and must directly engage rather than repeat itself. The loop exits on the first `accept: true`, up to 4 rounds.

Both agents run on **Claude Sonnet 4.6** — this loop is pure text reasoning, not generation, and is the one place in the pipeline where the model provider is intentionally decoupled from the agent's tools.

### 2. Creative Director

Reads the approved brief, generates diverse image prompts, calls Nano Banana Pro in parallel, then ranks the candidates with a Gemini Flash multimodal call (sends all images + the brief, asks for JSON scores weighted toward brand identity — "does this image show *this specific business*, not a generic shot of the product category?"). The winner becomes the hero. Music (Lyria) and voiceover (Gemini TTS) are generated concurrently.

### 3. Post-Production

Writes Veo motion descriptions for each candidate image, calls Veo 3.1 Lite image-to-video in parallel (one clip per image, each a long-running async operation polled to completion), concatenates the clips, and mixes with music and voiceover via FFmpeg — voiceover at full volume, music ducked 14 dB. Total video length scales with the number of candidate images.

Veo retries up to 3 times with backoff on transient backend failures. Safety-filtered content is not retried (same image+prompt would fail identically).

### 4. Feedback loop

The Supervisor (Gemini Flash) classifies the user's feedback and routes it to the exact responsible agent and asset:

- **Visual-only** (e.g. "I want people in the video") → Creative Director, images scope only → new image generation + Veo re-run with new footage
- **Audio-only** (e.g. "change the music to violin") → Creative Director, music scope only → Lyria regeneration + **remux using existing Veo clips** (no Veo re-run)
- **Brief-level** (e.g. "focus on the family-owned story") → Strategist revision → cascades through Director and Post-Production
- **Mix/motion** (e.g. "the voiceover is too quiet") → Post-Production only

Music and voiceover feedback rewrites the audio direction cleanly (via a Gemini Flash call) rather than appending new instructions to the stale old description — prevents Lyria from receiving contradictory instrumentation cues.

## What's real (no mocks)

- Web scraping: real BS4 + httpx, real CSS color/font extraction
- Site image analysis: real Gemini Flash multimodal call on downloaded image bytes
- Nano Banana Pro: real API calls, real PNGs
- Image ranker: real multimodal Gemini call, real JSON scores
- Lyria 3: real API call, real WAV
- Gemini TTS: real API call, real WAV with prosody hints
- Veo 3.1 Lite: real async operation, polled to completion, real MP4
- FFmpeg: real subprocess for concat + mux
- ADK `Runner`: real agent loops; the LLM decides when to call tools, when to call `submit_brief` with a rebuttal vs a revision

## Project layout

```
brandsync/
├── backend/
│   ├── Dockerfile              # python:3.11-slim + apt ffmpeg — needed because
│   │                           # generic buildpacks don't include ffmpeg
│   ├── app/
│   │   ├── agents/             # ADK agents, prompts, tool wrappers
│   │   ├── tools/              # real implementations: scraper, Nano Banana,
│   │   │                       # Lyria, TTS, Veo, FFmpeg, visual context analysis
│   │   ├── schemas/            # Pydantic contracts between agents
│   │   ├── api/                # FastAPI routes + SSE orchestrator
│   │   ├── storage/            # Supabase-backed session store + asset cache
│   │   ├── config.py           # all model IDs, API keys, settings
│   │   └── main.py
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    └── src/
        ├── pages/              # Home, Generation (sidebar layout)
        ├── components/         # AgentColumn (shows live critic/rebuttal cards),
        │                       # BriefCard, AssetGrid, VideoPlayer
        ├── api/client.js       # fetch + SSE, VITE_API_BASE_URL for production
        └── styles/
```

## Deploying

Backend needs a **persistent process** (not serverless — SSE connections stay open for minutes during generation) and `ffmpeg` as a system binary. The `Dockerfile` handles both.

Recommended free-tier path: **Render** (backend, no card required) + **Vercel** (frontend static) + **Supabase** (already required for storage).

1. Create the Supabase tables above if you haven't
2. On Render: New Web Service → connect repo → root dir `backend` → Docker runtime → add env vars (`GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `ALLOWED_ORIGINS` = your Vercel URL)
3. On Vercel: New Project → root dir `frontend` → add build env var `VITE_API_BASE_URL` = your Render URL

## Cost note

Veo and Lyria are paid preview APIs. A single end-to-end run costs a few US dollars at current AI Studio rates. The URL-based cache (Supabase `cached_generations`) skips all generation for repeat URLs. Don't leave the feedback loop running in a browser tab.

## Roadmap

- A2A protocol so agents can be deployed as independent services
- Retry logic for Lyria, TTS, and Nano Banana on transient API failures (Veo already has retries)
- robots.txt check in the scraper before public deployment
