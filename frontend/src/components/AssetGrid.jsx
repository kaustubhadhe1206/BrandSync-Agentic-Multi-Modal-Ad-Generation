// The candidate grid: shows all 4 Nano Banana images with the winner
// highlighted in coral. Click any to see the ranker's reasoning.

import React, { useState } from 'react';
import { pathToArtifact, selectHero } from '../api/client.js';

export default function AssetGrid({ sessionId, rankedImages, bundle, onHeroChanged }) {
  const [selected, setSelected] = useState(null);
  const [overriding, setOverriding] = useState(false);

  if (!rankedImages || rankedImages.length === 0) return null;

  // Sort: winner first
  const sorted = [...rankedImages].sort((a, b) => b.score - a.score);
  const winnerIndex = sorted[0].candidate.index;

  async function useAsHero(candidateIndex) {
    setOverriding(true);
    try {
      await selectHero(sessionId, candidateIndex);
      onHeroChanged?.();
    } catch (e) {
      console.error('select-hero failed', e);
    } finally {
      setOverriding(false);
    }
  }

  return (
    <div className="slate-frame p-6">
      <div className="flex items-baseline justify-between mb-4">
        <span className="eyebrow">The Candidates</span>
        <span className="font-mono text-[11px] text-ink-400">
          Ranked by Gemini · every shot becomes a Veo clip, hero plays first
        </span>
      </div>

      <h3 className="font-display font-semibold text-[28px] leading-[1] tracking-tightest mb-5">
        {sorted.length} shots. <span className="font-semibold text-coral">One ad.</span>
      </h3>

      <div
        className="grid gap-3 mb-5"
        style={{ gridTemplateColumns: `repeat(${sorted.length}, minmax(0, 1fr))` }}
      >
        {sorted.map((r) => {
          const isWinner = r.candidate.index === winnerIndex;
          const isSelected = selected?.candidate.index === r.candidate.index;
          const src = pathToArtifact(sessionId, r.candidate.path);
          return (
            <button
              key={r.candidate.index}
              onClick={() => setSelected(r)}
              className={`group relative aspect-square overflow-hidden rounded-xl border transition
                ${isWinner ? 'border-coral shadow-[0_0_24px_rgba(124,92,252,0.25)]' : 'border-ink-700 hover:border-ink-500'}
                ${isSelected ? 'ring-1 ring-bone/40' : ''}
              `}
            >
              {src && (
                <img
                  src={src}
                  alt={`Candidate ${r.candidate.index}`}
                  className="w-full h-full object-cover"
                />
              )}
              <div className="absolute top-1.5 left-1.5 font-mono text-[10px] bg-ink-900/80 rounded-md px-1.5 py-0.5 text-bone/90">
                0{r.candidate.index + 1}
              </div>
              <div className="absolute bottom-1.5 right-1.5 font-mono text-[10px] bg-ink-900/80 rounded-md px-1.5 py-0.5 tabular-nums">
                {r.score.toFixed(1)}
              </div>
              {isWinner && (
                <div className="absolute bottom-1.5 left-1.5 font-mono text-[10px] bg-coral text-bone rounded-md px-1.5 py-0.5 uppercase tracking-wider">
                  Hero
                </div>
              )}
            </button>
          );
        })}
      </div>

      {selected && (
        <div className="rule pt-4">
          <div className="flex items-baseline justify-between mb-2">
            <span className="eyebrow">Director's note · Image 0{selected.candidate.index + 1}</span>
            {selected.candidate.index !== winnerIndex && (
              <button
                onClick={() => useAsHero(selected.candidate.index)}
                disabled={overriding}
                className="font-mono text-[11px] uppercase tracking-[0.15em] text-bone/80 hover:text-coral border border-ink-700 hover:border-coral rounded-full px-3 py-1.5 transition disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {overriding ? 'Re-rendering…' : 'Lead with this shot instead'}
              </button>
            )}
          </div>
          <p className="text-[14px] leading-snug text-bone/90">
            "{selected.reasoning}"
          </p>
        </div>
      )}

      {bundle && (
        <div className="rule mt-5 pt-5 grid grid-cols-2 gap-6">
          <AudioPreview
            label="Music · Lyria 3"
            src={pathToArtifact(sessionId, bundle.music_path)}
            caption={bundle.music_prompt}
          />
          <AudioPreview
            label="Voiceover · Gemini TTS"
            src={pathToArtifact(sessionId, bundle.voiceover_path)}
            caption={`${bundle.voiceover_duration_sec?.toFixed(1)}s — ${bundle.voiceover_script}`}
          />
        </div>
      )}
    </div>
  );
}

function AudioPreview({ label, src, caption }) {
  return (
    <div>
      <div className="eyebrow mb-2">{label}</div>
      {src && (
        <audio controls src={src} className="w-full h-8 mb-2 rounded-lg" style={{ filter: 'invert(0.9) hue-rotate(180deg)' }} />
      )}
      <p className="text-[12px] text-ink-400 leading-snug">{caption}</p>
    </div>
  );
}
