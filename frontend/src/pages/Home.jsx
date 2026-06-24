// Landing page. The hero is the thesis: "From URL to cinema in minutes."
// One input, one button — restraint. The agency story is told in the small
// type underneath: 3 agents, each described in one sharp line.

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { startGeneration } from '../api/client.js';

const AGENTS = [
  { num: '01', name: 'Strategist', line: 'Reads your site. Writes the brief.', model: 'Gemini 3.1 Pro' },
  { num: '02', name: 'Director',   line: 'Casts the image. Composes the score.', model: 'Nano Banana + Lyria' },
  { num: '03', name: 'Post',       line: 'Films the ad. Cuts the audio.', model: 'Veo 3.1' },
];

export default function Home() {
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [forceRegenerate, setForceRegenerate] = useState(false);
  const nav = useNavigate();

  async function submit(e) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const normalized = url.startsWith('http') ? url : `https://${url}`;
      const { session_id } = await startGeneration(normalized, forceRegenerate);
      nav(`/g/${session_id}`);
    } catch (e) {
      setErr(e.message || 'Failed to start');
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top bar */}
      <header className="px-10 py-6 flex items-baseline justify-between border-b border-ink-700">
        <div className="font-display font-bold text-[22px] tracking-tightest">
          Brand<span className="text-coral">Sync</span>
        </div>
        <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-400">
          A creative team that is mostly software
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1 px-10 grid grid-cols-12 gap-10 items-center">
        <div className="col-span-7 max-w-2xl">
          <p className="eyebrow mb-6">From a URL · A cinematic ad · In minutes</p>

          <h1 className="font-display font-extrabold text-[80px] leading-[0.95] tracking-tightest mb-8">
            Hand us a website.<br />
            <span className="text-coral">We&apos;ll hand you</span><br />
            a film.
          </h1>

          <p className="text-[16px] text-bone/70 leading-relaxed mb-10 max-w-lg">
            Three specialist agents — a Strategist, a Creative Director, and a
            Post-Production lead — read your site, argue about your brand, and
            produce a finished cinematic video ad. You watch them work.
          </p>

          <form onSubmit={submit} className="flex gap-3 max-w-xl">
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="tonyspizza.com"
              disabled={busy}
              autoFocus
              className="flex-1 bg-ink-800 border border-ink-700 rounded-xl px-5 py-4 text-[16px] text-bone placeholder-ink-500 focus:outline-none focus:border-coral transition"
            />
            <button
              type="submit"
              disabled={busy || !url.trim()}
              className="bg-coral hover:bg-coral-dark text-bone font-medium rounded-xl px-8 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_32px_rgba(124,92,252,0.35)] hover:shadow-[0_0_40px_rgba(124,92,252,0.5)]"
            >
              {busy ? 'Starting…' : 'Begin'}
            </button>
          </form>

          {err && (
            <p className="mt-4 text-[13px] text-coral">{err}</p>
          )}

          <label className="mt-5 flex items-center gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={forceRegenerate}
              onChange={(e) => setForceRegenerate(e.target.checked)}
              disabled={busy}
              className="accent-coral"
            />
            <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-ink-400">
              Force regenerate — skip the cached result for this site, if any
            </span>
          </label>
        </div>

        {/* The team — three numbered cards, demonstrating the architecture */}
        <div className="col-span-5">
          <div className="eyebrow mb-4">The Team</div>
          <div>
            {AGENTS.map((a, i) => (
              <div key={a.num}>
                {i > 0 && <div className="ml-[26px] h-4 border-l-2 border-dotted border-ink-600" />}
                <div className="slate-frame px-5 py-4 flex items-baseline gap-5">
                  <span className="font-mono text-[12px] text-ink-400">{a.num}</span>
                  <div className="flex-1">
                    <div className="flex items-baseline justify-between gap-3">
                      <div className="font-display font-semibold text-[22px] leading-none tracking-tightest">
                        {a.name}
                      </div>
                      <span className="pill">
                        <span className="pill-dot bg-live" />
                        {a.model}
                      </span>
                    </div>
                    <div className="text-[12px] text-ink-400 mt-1.5">{a.line}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="rule mt-8 pt-5">
            <div className="eyebrow mb-2">Built on</div>
            <div className="font-mono text-[11px] text-bone/60 leading-relaxed">
              Gemini 3 Pro · Nano Banana Pro · Veo 3.1 · Lyria 3 · Gemini TTS<br />
              Orchestrated with Google ADK
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
