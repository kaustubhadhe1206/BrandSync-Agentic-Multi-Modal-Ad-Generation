// The control room. Sidebar holds the 3 agents (own scroll); main panel
// holds outputs as they arrive (own scroll) — two independent panes so
// neither ever covers or pushes the other out of view.

import React, { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { openEventStream, getSession, resumeSession } from '../api/client.js';
import AgentColumn from '../components/AgentColumn.jsx';
import BriefCard from '../components/BriefCard.jsx';
import AssetGrid from '../components/AssetGrid.jsx';
import VideoPlayer from '../components/VideoPlayer.jsx';

const AGENTS = [
  {
    key: 'strategist',
    num: 1,
    name: 'Strategist',
    subtitle: 'Reads the site. Writes the brief.',
  },
  {
    key: 'creative_director',
    num: 2,
    name: 'Director',
    subtitle: 'Casts the image. Composes the score.',
  },
  {
    key: 'post_production',
    num: 3,
    name: 'Post',
    subtitle: 'Films the ad. Cuts the audio.',
  },
];

export default function Generation() {
  const { sessionId } = useParams();
  const [events, setEvents] = useState([]);
  const [session, setSession] = useState(null);
  const [streamClosed, setStreamClosed] = useState(false);
  const [activeAgent, setActiveAgent] = useState('strategist');
  const [retrying, setRetrying] = useState(false);

  // Open SSE stream
  useEffect(() => {
    if (!sessionId) return;
    const stream = openEventStream(sessionId, {
      onEvent: (ev) => {
        setEvents((prev) => [...prev, ev]);

        // Track active agent: the most recent non-system author
        if (ev.agent && ev.agent !== 'system') {
          setActiveAgent(ev.agent);
        }
      },
      onEnd: () => {
        setStreamClosed(true);
        // Pull final state
        getSession(sessionId).then(setSession).catch(console.error);
      },
      onError: (e) => console.error('SSE error', e),
    });
    return () => stream.close();
  }, [sessionId]);

  // Poll session state once we've seen the supervisor's "handoff" so brief shows up early
  useEffect(() => {
    let cancelled = false;
    const lastBrief = events.find(
      (e) => e.agent === 'strategist' && e.data?.brief
    );
    const lastBundle = events.find(
      (e) => e.agent === 'creative_director' && e.data?.asset_bundle
    );
    const lastDone = events.find((e) => e.kind === 'done');

    if (lastBrief || lastBundle || lastDone) {
      getSession(sessionId)
        .then((s) => { if (!cancelled) setSession(s); })
        .catch(() => {});
    }
    return () => { cancelled = true; };
  }, [events, sessionId]);

  // Per-agent state derived from events
  const agentEvents = useMemo(() => {
    const buckets = { strategist: [], creative_director: [], post_production: [], supervisor: [], system: [] };
    for (const ev of events) {
      const k = ev.agent in buckets ? ev.agent : 'system';
      // Map critic events into strategist column (they're a sub-role)
      if (ev.agent === 'critic') {
        buckets.strategist.push(ev);
      } else {
        buckets[k].push(ev);
      }
    }
    return buckets;
  }, [events]);

  // Processed in chronological order so a later handoff (a revision
  // starting) correctly overrides an earlier "done" from the initial run or
  // a previous revision, and a later completion marker flips it back to
  // done. The old version used `.find()` (first match wins), which could
  // never un-stick an agent from "done" once any completion event had ever
  // appeared for it — exactly why a feedback revision looked like nothing
  // was happening: every stage was already "done" from the first run and
  // stayed that way forever.
  const agentState = useMemo(() => {
    const result = { strategist: 'idle', creative_director: 'idle', post_production: 'idle' };
    for (const ev of events) {
      const phase = ev.data?.phase;
      if (!phase || !(phase in result)) continue;
      if (ev.kind === 'handoff') {
        result[phase] = 'active';
      } else if (
        (phase === 'strategist' && ev.data?.brief) ||
        (phase === 'creative_director' && ev.data?.asset_bundle) ||
        (phase === 'post_production' && ev.kind === 'done')
      ) {
        result[phase] = 'done';
      }
    }
    return result;
  }, [events]);

  // Supervisor classifies feedback but isn't one of the 3 pipeline columns,
  // so its activity gets a transient banner instead of its own card —
  // otherwise the classification step was invisible.
  const lastPostProductionDone = useMemo(
    () => [...events].reverse().find((e) => e.data?.phase === 'post_production' && e.kind === 'done'),
    [events]
  );

  const lastSupervisorEvent = useMemo(() => {
    const supervisorEvents = events.filter((e) => e.agent === 'supervisor');
    return supervisorEvents.length ? supervisorEvents[supervisorEvents.length - 1] : null;
  }, [events]);

  // A feedback round is "in flight" once the supervisor starts classifying
  // it, until the next final-video "done" arrives after that point.
  const isRevising = Boolean(
    lastSupervisorEvent && (!lastPostProductionDone || lastSupervisorEvent.timestamp > lastPostProductionDone.timestamp)
  );

  const supervisorBanner = isRevising ? lastSupervisorEvent.text : null;

  // Cache-busts the video URL per revision — final.mp4 is always the same
  // filename/path, so without this the browser can keep showing the old
  // bytes for a session it already fetched that URL for.
  const videoVersion = lastPostProductionDone?.timestamp ?? 0;

  const brief = session?.state?.brand_brief;
  const ranked = session?.state?.ranked_images;
  const bundle = session?.state?.asset_bundle;
  const finalVideo = session?.state?.final_video_path;
  const duration = session?.state?.final_duration;
  const hasError = session?.error;

  // Reset stream consumption and reopen — used whenever a background action
  // (feedback, retry, hero override) queues new agent activity on this session.
  // Deliberately does NOT clear `session` — the existing brief/assets/video
  // stay on screen (the video gets a "revising" overlay instead of
  // vanishing) until a fresh getSession() call replaces them once the new
  // round actually produces something. We deliberately don't store the
  // stream handle here either; cleanup is owned by the main effect.
  function reopenStream() {
    setEvents([]);
    setStreamClosed(false);
    openEventStream(sessionId, {
      onEvent: (ev) => setEvents((prev) => [...prev, ev]),
      onEnd: () => {
        setStreamClosed(true);
        getSession(sessionId).then(setSession).catch(console.error);
      },
    });
  }

  function handleFeedbackSubmitted() {
    reopenStream();
  }

  function handleHeroChanged() {
    reopenStream();
  }

  async function handleRetry() {
    setRetrying(true);
    try {
      await resumeSession(sessionId);
      reopenStream();
    } catch (e) {
      console.error('resume failed', e);
    } finally {
      setRetrying(false);
    }
  }

  const isLive = !streamClosed || hasError;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar — the 3 agents, stacked. Its own independent scroll, so a
          long transcript never pushes the outputs panel around or gets
          scrolled out of view (the bug in the previous sticky-header
          version: outputs growing below pushed the live transcripts off
          screen, and a translucent sticky header bled the content behind
          it through on top of that). */}
      <aside className="w-[360px] shrink-0 h-screen overflow-y-auto border-r border-ink-700 bg-ink-900 px-6 py-6">
        <a href="/" className="font-display font-bold text-[20px] tracking-tightest">
          Brand<span className="text-coral">Sync</span>
        </a>
        <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.15em] text-ink-400">
          Session · {sessionId}
        </div>

        <div className="inline-flex items-center gap-2 mt-4 mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-400">
          {isLive && <span className="live-dot" />}
          {streamClosed && !hasError ? 'Pipeline complete' : 'Live'}
        </div>

        {supervisorBanner && (
          <div className="mb-5 flex items-start gap-2 rounded-xl border border-ink-600 bg-ink-700/40 px-3 py-2.5">
            <span className="pill-dot bg-live animate-live-pulse mt-1 shrink-0" />
            <p className="text-[12px] leading-snug text-bone/85">
              <span className="font-mono uppercase tracking-[0.1em] text-ink-400">Supervisor · </span>
              {supervisorBanner}
            </p>
          </div>
        )}

        <div className="eyebrow mb-3">The Team</div>
        <div>
          {AGENTS.map((a, i) => (
            <div key={a.key}>
              {i > 0 && <div className="ml-[22px] h-4 border-l-2 border-dotted border-ink-600" />}
              <AgentColumn
                number={a.num}
                name={a.name}
                subtitle={a.subtitle}
                state={agentState[a.key]}
                events={agentEvents[a.key] || []}
              />
            </div>
          ))}
        </div>
      </aside>

      {/* Outputs — independently scrollable main panel */}
      <main className="flex-1 h-screen overflow-y-auto px-10 py-8">
        <div className="flex items-baseline justify-between mb-8">
          <h1 className="font-display font-bold text-[32px] tracking-tightest leading-none">
            The team is at work.
          </h1>
          <span className="eyebrow">Outputs appear as each agent finishes</span>
        </div>

        <div className="space-y-8">
          {brief && <BriefCard brief={brief} />}
          {ranked && ranked.length > 0 && (
            <AssetGrid
              sessionId={sessionId}
              rankedImages={ranked}
              bundle={bundle}
              onHeroChanged={handleHeroChanged}
            />
          )}
          {finalVideo && (
            <VideoPlayer
              sessionId={sessionId}
              videoPath={finalVideo}
              videoVersion={videoVersion}
              duration={duration}
              isRevising={isRevising}
              onFeedbackSubmitted={handleFeedbackSubmitted}
            />
          )}

          {hasError && (
            <div className="slate-frame p-6">
              <div className="flex items-baseline justify-between mb-2">
                <span className="eyebrow text-coral">Error</span>
                <button
                  onClick={handleRetry}
                  disabled={retrying}
                  className="font-mono text-[11px] uppercase tracking-[0.15em] text-bone/80 hover:text-coral border border-ink-700 hover:border-coral rounded-full px-3 py-1.5 transition disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {retrying ? 'Resuming…' : 'Retry from last stage'}
                </button>
              </div>
              <p className="text-[14px] text-bone/85">{hasError}</p>
            </div>
          )}

          {!brief && !hasError && (
            <div className="slate-frame p-6 text-center">
              <p className="text-[13px] text-ink-400">
                Outputs will land here as the Strategist, Director, and Post-Production agents finish their work.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
