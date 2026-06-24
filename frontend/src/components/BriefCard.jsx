// Renders the StyleContract / BrandBrief that the Strategist hands off.
// Uses the brief's own palette as accent colors — a small but pleasing touch
// that makes each generation feel custom.

import React from 'react';

function Swatch({ hex, label }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="w-4 h-4 rounded-md border border-ink-700"
        style={{ backgroundColor: hex }}
      />
      <span className="font-mono text-[11px] text-ink-400">{label}</span>
      <span className="font-mono text-[11px] text-bone/70">{hex}</span>
    </div>
  );
}

export default function BriefCard({ brief }) {
  if (!brief) return null;
  const p = brief.palette || {};

  return (
    <div className="slate-frame p-6">
      <div className="flex items-baseline justify-between mb-4">
        <span className="eyebrow">The Brief</span>
        <span className="pill">
          <span className="pill-dot bg-coral" />
          From: Strategist
        </span>
      </div>

      <h3 className="font-display font-semibold text-[40px] leading-[0.95] tracking-tightest mb-1">
        {brief.business_name}
      </h3>
      <p className="text-[16px] text-bone/70 mb-4">
        {brief.one_liner}
      </p>

      {brief.visual?.mood?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6">
          {brief.visual.mood.map((m) => (
            <span key={m} className="pill">{m}</span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-8 gap-y-5 mb-6">
        <Field label="Audience" value={brief.target_audience} />
        <Field label="Core message" value={brief.core_message} />
        <Field label="Aesthetic" value={brief.visual?.aesthetic} />
        <Field label="Photography" value={brief.visual?.photography_style} />
        <Field label="Music direction" value={brief.audio?.music_genre} />
        <Field label="Voiceover tone" value={brief.audio?.voiceover_tone} />
      </div>

      <div className="rule pt-4 mb-4">
        <div className="eyebrow mb-3">Palette</div>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Swatch hex={p.primary} label="Primary" />
          <Swatch hex={p.secondary} label="Secondary" />
          <Swatch hex={p.accent} label="Accent" />
          <Swatch hex={p.neutral} label="Neutral" />
        </div>
      </div>

      <div className="rule pt-4">
        <div className="eyebrow mb-2">Voiceover script</div>
        <p className="font-display font-medium text-[20px] leading-snug text-bone">
          &ldquo;{brief.voiceover_script}&rdquo;
        </p>
      </div>
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div>
      <div className="eyebrow mb-1">{label}</div>
      <div className="text-[13px] text-bone/85 leading-snug">{value}</div>
    </div>
  );
}
