// Indeterminate loading bar for in-progress agent/tool activity. No real
// percentage exists for most steps (Veo polls a long-running op with no
// progress callback), so this is a shimmer animation, paired with an
// elapsed-time readout where the caller has one (see AgentColumn).

import React from 'react';

export default function ProgressBar({ className = '' }) {
  return (
    <div className={`progress-track ${className}`}>
      <div className="progress-fill animate-shimmer" />
    </div>
  );
}
