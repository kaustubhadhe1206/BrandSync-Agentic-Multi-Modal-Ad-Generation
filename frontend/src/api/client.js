// Thin API wrapper. Relative URLs in dev (Vite proxy forwards /api/* to the
// local backend). In production the frontend and backend are on different
// domains — VITE_API_BASE_URL (set at build time) points at the deployed
// backend; unset, this falls back to '' so local dev is unaffected.

const BASE = import.meta.env.VITE_API_BASE_URL || '';

export async function startGeneration(url, forceRegenerate = false) {
  const r = await fetch(`${BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, force_regenerate: forceRegenerate }),
  });
  if (!r.ok) throw new Error(`generate failed: ${r.status}`);
  return r.json(); // { session_id }
}

export async function getSession(sessionId) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}`);
  if (!r.ok) throw new Error(`session fetch failed: ${r.status}`);
  return r.json();
}

export async function sendFeedback(sessionId, feedback) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
  if (!r.ok) throw new Error(`feedback failed: ${r.status}`);
  return r.json();
}

export async function resumeSession(sessionId) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/resume`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`resume failed: ${r.status}`);
  return r.json();
}

export async function selectHero(sessionId, candidateIndex) {
  const r = await fetch(`${BASE}/api/sessions/${sessionId}/select-hero`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_index: candidateIndex }),
  });
  if (!r.ok) throw new Error(`select-hero failed: ${r.status}`);
  return r.json();
}

// Open an EventSource for the live agent stream.
// Returns { close } so the caller can disconnect.
export function openEventStream(sessionId, { onEvent, onEnd, onError }) {
  const es = new EventSource(`${BASE}/api/sessions/${sessionId}/events`);

  // Backend uses named SSE events — we listen on each kind so onEvent gets clean payloads.
  const kinds = ['thinking', 'tool_call', 'tool_result', 'message', 'handoff', 'error', 'done'];
  kinds.forEach((kind) => {
    es.addEventListener(kind, (e) => {
      try {
        onEvent?.(JSON.parse(e.data));
      } catch (err) {
        console.error('parse SSE', err);
      }
    });
  });
  es.addEventListener('end', () => {
    onEnd?.();
    es.close();
  });
  es.onerror = (e) => {
    onError?.(e);
  };

  return { close: () => es.close() };
}

export function artifactUrl(sessionId, relativePath) {
  // relativePath looks like "images/cand_0_ab1234.png" or "final.mp4"
  return `${BASE}/api/artifacts/${sessionId}/${relativePath}`;
}

// Helper to extract the relative path from an absolute path the backend returned.
// Cached results point straight at Supabase Storage (a full https:// URL) —
// pass those through unchanged instead of routing through /api/artifacts.
export function pathToArtifact(sessionId, absPath) {
  if (!absPath) return null;
  if (/^https?:\/\//i.test(absPath)) return absPath;
  const marker = `/${sessionId}/`;
  const idx = absPath.indexOf(marker);
  if (idx === -1) return null;
  return artifactUrl(sessionId, absPath.slice(idx + marker.length));
}
