"""FFmpeg synchronization engine. Combines Veo video + Lyria music + TTS voiceover
into a single MP4 with proper audio mixing.

Real ffmpeg subprocess; no mocks. Requires ffmpeg installed on the system.
"""
from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path

from ..config import settings


async def _run_ffmpeg(args: list[str]) -> None:
    # asyncio.create_subprocess_exec needs ProactorEventLoop on Windows, but
    # google-adk's grpc transport forces SelectorEventLoop (no subprocess
    # support there) — run via a worker thread instead, same pattern used
    # for every other blocking SDK call in this codebase.
    def _call() -> subprocess.CompletedProcess:
        return subprocess.run([settings.FFMPEG_PATH, *args], capture_output=True)

    result = await asyncio.to_thread(_call)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}):\n"
            f"command: {settings.FFMPEG_PATH} {' '.join(shlex.quote(a) for a in args)}\n"
            f"stderr: {result.stderr.decode(errors='replace')[-2000:]}"
        )


async def sync_video_audio(
    video_paths: list[str],
    music_path: str,
    voiceover_path: str,
    session_id: str,
    voiceover_volume_db: float = 0.0,
    music_volume_db: float = -14.0,
) -> tuple[str, float]:
    """Concatenate the Veo clips in order, then mux with mixed audio.
    Returns (output_path, duration_sec).

    Audio mix strategy:
    - Voiceover at near-full volume (0 dB)
    - Music ducked by ~14 dB so VO sits clearly on top
    - Both tracks trimmed/looped to match the concatenated video's duration

    Concatenation uses the concat *filter* (decode+re-encode), not the concat
    demuxer, since the clips come from separate Veo calls and aren't
    guaranteed stream-identical enough for a lossless copy-concat.
    """
    out_dir = settings.OUTPUT_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "final.mp4"

    # 1. Probe each clip and sum durations — that's the concatenated length
    # we trim/pad audio to.
    clip_durations = [await _probe_duration(p) for p in video_paths]
    total_duration = sum(clip_durations)

    # 2. Build a single ffmpeg invocation that:
    #    - decodes + concatenates the video clips in order
    #    - takes music (loops if shorter than the total, trimmed to match)
    #    - takes voiceover (padded with silence if shorter)
    #    - mixes the two audio tracks with volume adjustments
    n = len(video_paths)
    music_idx = n
    voice_idx = n + 1

    inputs: list[str] = []
    for p in video_paths:
        inputs += ["-i", p]
    inputs += ["-stream_loop", "-1", "-i", music_path]
    inputs += ["-i", voiceover_path]

    video_chain = "".join(f"[{i}:v]setpts=PTS-STARTPTS[v{i}];" for i in range(n))
    concat_refs = "".join(f"[v{i}]" for i in range(n))

    args = [
        "-y",
        *inputs,
        "-filter_complex",
        (
            f"{video_chain}"
            f"{concat_refs}concat=n={n}:v=1:a=0[vout];"
            f"[{music_idx}:a]volume={music_volume_db}dB,atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS[bg];"
            f"[{voice_idx}:a]volume={voiceover_volume_db}dB,apad,atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS[vo];"
            f"[bg][vo]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        ),
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    await _run_ffmpeg(args)
    return out_path.as_posix(), total_duration


async def _probe_duration(path: str) -> float:
    def _call() -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                settings.FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
        )

    result = await asyncio.to_thread(_call)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.decode(errors='replace')}")
    return float(result.stdout.decode().strip())
