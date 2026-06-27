// The signature element: each agent gets a column showing its live activity.
// The active agent's column glows amber; completed columns get a violet edge.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import ProgressBar from './ProgressBar.jsx';

function StateIndicator({ state }) {
  if (state === 'active') return (
    <span className="inline-flex items-center gap-1.5">
      <span className="live-dot" />
      <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-live">Working</span>
    </span>
  );
  if (state === 'done') return (
    <span className="inline-flex items-center gap-1.5">
      <span className="done-dot" />
      <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-coral">Complete</span>
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="idle-dot" />
      <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-ink-400">Standby</span>
    </span>
  );
}

// A tool_call with no later tool_result for the same tool is still running.
function findPendingCall(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev.kind === 'tool_result') return null;
    if (ev.kind === 'tool_call') return ev;
  }
  return null;
}

// The Critic's message is raw JSON ({accept, reason, requested_changes}) —
// parse it so we can render a real callout instead of a JSON blob. Strips
// code fences defensively, same as the backend's own _parse_critique.
function tryParseCritique(text) {
  if (!text) return null;
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  try {
    const parsed = JSON.parse(cleaned);
    return parsed && typeof parsed === 'object' && 'accept' in parsed ? parsed : null;
  } catch {
    return null;
  }
}

function CritiqueCard({ critique }) {
  const accepted = Boolean(critique.accept);
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${accepted ? 'border-coral/40 bg-coral/5' : 'border-ink-600 bg-ink-800/60'}`}>
      <span className={`font-mono text-[10px] uppercase tracking-[0.15em] ${accepted ? 'text-coral' : 'text-ink-400'}`}>
        {accepted ? '✓ Brief accepted' : '✕ Revision requested'}
      </span>
      {critique.reason && (
        <p className="mt-1 text-[12px] text-bone/85 leading-snug">{critique.reason}</p>
      )}
      {!accepted && Array.isArray(critique.requested_changes) && critique.requested_changes.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {critique.requested_changes.map((c, i) => (
            <li key={i} className="text-[11px] text-ink-400 leading-snug">· {c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RebuttalCard({ rebuttal }) {
  return (
    <div className="rounded-lg border border-coral/40 bg-coral/5 px-3 py-2.5">
      <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-coral">
        ↩ Strategist pushes back
      </span>
      <p className="mt-1 text-[12px] text-bone/85 leading-snug">{rebuttal}</p>
    </div>
  );
}

function EventRow({ ev }) {
  const time = new Date(ev.timestamp * 1000).toLocaleTimeString(undefined, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  const isToolCall = ev.kind === 'tool_call';
  const isError = ev.kind === 'error';
  const isCritic = ev.agent === 'critic';
  const rebuttal = isToolCall && ev.data?.tool_name === 'submit_brief' ? ev.data?.args?.rebuttal : null;
  const critique = isCritic && ev.kind === 'message' ? tryParseCritique(ev.text) : null;

  return (
    <div className="animate-slide-up py-2.5 first:pt-0">
      <div className="flex gap-3 items-baseline">
        <span className="font-mono text-[10px] text-ink-500 shrink-0 tabular-nums">{time}</span>
        <div className="flex-1 min-w-0 space-y-1.5">
          {isCritic && (
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-400">
              ⟲ Critic
            </div>
          )}
          {isToolCall && (
            <div className="font-mono text-[12px] text-coral mb-0.5">
              → {ev.data?.tool_name}()
            </div>
          )}
          {isError && (
            <div className="font-mono text-[12px] text-coral mb-0.5">ERROR</div>
          )}

          {critique ? (
            <CritiqueCard critique={critique} />
          ) : (
            <div className={`text-[13px] leading-snug whitespace-pre-wrap break-words ${isError ? 'text-coral' : 'text-bone/85'}`}>
              {ev.text}
            </div>
          )}

          {rebuttal && <RebuttalCard rebuttal={rebuttal} />}
        </div>
      </div>
    </div>
  );
}

export default function AgentColumn({ number, name, subtitle, state, events }) {
  const scrollRef = useRef(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  const pending = useMemo(() => findPendingCall(events), [events]);

  // Tick once a second only while something is actually pending, so idle/done
  // columns don't re-render for no reason.
  useEffect(() => {
    if (!pending) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [pending]);

  const elapsedSec = pending ? Math.max(0, Math.floor(now / 1000 - pending.timestamp)) : 0;

  const frameClass =
    state === 'active' ? 'slate-frame slate-frame--active'
    : state === 'done' ? 'slate-frame slate-frame--done'
    : 'slate-frame';

  return (
    <div className={`${frameClass} flex flex-col overflow-hidden`}>
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-ink-700">
        <div className="flex items-baseline justify-between mb-2">
          <span className="font-mono text-[11px] tracking-[0.18em] text-ink-400">
            0{number}
          </span>
          <StateIndicator state={state} />
        </div>
        <h2 className="font-display font-semibold text-[20px] leading-[1.05] tracking-tightest text-bone">
          {name}
        </h2>
        <p className="mt-1 text-[11px] text-ink-400 leading-snug">{subtitle}</p>

        {state === 'active' && (
          <div className="mt-3">
            <ProgressBar />
            {pending && (
              <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
                {pending.data?.tool_name}() running · {elapsedSec}s
              </div>
            )}
          </div>
        )}
      </div>

      {/* Live transcript — bounded height, own scroll, so one long-running
          agent doesn't blow out the whole sidebar */}
      <div
        ref={scrollRef}
        className="overflow-y-auto px-4 py-2 divide-y divide-ink-700/60"
        style={{ maxHeight: 260 }}
      >
        {events.length === 0 ? (
          <div className="py-6 text-center">
            <p className="text-[13px] text-ink-500">
              Waiting for handoff
            </p>
          </div>
        ) : (
          events.map((ev, i) => <EventRow key={i} ev={ev} />)
        )}
      </div>
    </div>
  );
}
