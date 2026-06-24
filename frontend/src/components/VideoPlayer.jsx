// Final cut player + feedback composer.
// The feedback box has suggested prompts that demonstrate the routing logic:
// each example clearly belongs to a different agent.

import React, { useState } from 'react';
import { pathToArtifact, sendFeedback } from '../api/client.js';
import ProgressBar from './ProgressBar.jsx';

const SUGGESTIONS = [
  { text: 'Switch the music to mellow jazz with brushed drums', target: 'Director' },
  { text: 'Lead with the family-owned story, less product-forward', target: 'Strategist' },
  { text: 'Bring the voiceover up — music is overpowering it', target: 'Post-Production' },
];

export default function VideoPlayer({ sessionId, videoPath, videoVersion, duration, isRevising, onFeedbackSubmitted }) {
  const [text, setText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const baseSrc = pathToArtifact(sessionId, videoPath);
  // final.mp4 is always the same filename/path for a session, so without a
  // cache-busting param the browser can keep showing the bytes it already
  // fetched for that URL even after the file on disk has been overwritten
  // by a revision.
  const src = baseSrc && videoVersion ? `${baseSrc}${baseSrc.includes('?') ? '&' : '?'}v=${videoVersion}` : baseSrc;

  async function submit() {
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      await sendFeedback(sessionId, text.trim());
      onFeedbackSubmitted?.(text.trim());
      setText('');
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="slate-frame p-6">
      <div className="flex items-baseline justify-between mb-4">
        <span className="eyebrow">Final Cut</span>
        <div className="flex items-center gap-4">
          {isRevising ? (
            <span className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-live">
              <span className="live-dot" /> Revising…
            </span>
          ) : (
            <span className="font-mono text-[11px] text-ink-400">
              {duration?.toFixed(1)}s · MP4
            </span>
          )}
          {src && (
            <a
              href={src}
              download={`brandsync-ad-${sessionId}.mp4`}
              className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-bone/80 hover:text-coral border border-ink-700 hover:border-coral rounded-full px-3 py-1.5 transition"
            >
              ↓ Download
            </a>
          )}
        </div>
      </div>

      <h3 className="font-display font-semibold text-[44px] leading-[0.95] tracking-tightest mb-6">
        {isRevising ? 'Revising your ad…' : 'Your ad is ready.'}
      </h3>

      {src && (
        <div className="relative bg-black border border-ink-700 rounded-xl overflow-hidden mb-6">
          <video
            controls
            src={src}
            className={`w-full transition ${isRevising ? 'opacity-40 blur-[2px]' : ''}`}
            style={{ maxHeight: 480 }}
          />
          {isRevising && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-ink-900/30">
              <div className="w-40">
                <ProgressBar />
              </div>
              <p className="font-mono text-[11px] uppercase tracking-[0.15em] text-bone/90">
                Re-rendering the final cut…
              </p>
            </div>
          )}
        </div>
      )}

      <div className="rule pt-5">
        <div className="eyebrow mb-3">Iterate · Send the team a note</div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What should change?"
          disabled={isRevising}
          className="w-full bg-ink-800 border border-ink-700 rounded-xl px-4 py-3 text-[14px] text-bone placeholder-ink-500 resize-none focus:outline-none focus:border-coral transition mb-3 disabled:opacity-50"
          rows={3}
        />

        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.text}
                onClick={() => setText(s.text)}
                className="group text-left px-3 py-1.5 border border-ink-700 hover:border-ink-500 rounded-lg transition disabled:opacity-40 disabled:cursor-not-allowed"
                disabled={submitting || isRevising}
              >
                <span className="font-mono text-[10px] text-ink-400 group-hover:text-bone/70 uppercase tracking-wider">
                  → {s.target}
                </span>
                <div className="text-[12px] text-bone/80 mt-0.5 max-w-[200px] leading-snug">
                  {s.text}
                </div>
              </button>
            ))}
          </div>

          <button
            onClick={submit}
            disabled={submitting || isRevising || !text.trim()}
            className="shrink-0 bg-coral hover:bg-coral-dark text-bone font-medium tracking-wide rounded-xl px-6 py-3 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_28px_rgba(124,92,252,0.3)] hover:shadow-[0_0_36px_rgba(124,92,252,0.45)]"
          >
            {isRevising ? 'Revising…' : submitting ? 'Sending…' : 'Send to team'}
          </button>
        </div>
      </div>
    </div>
  );
}
