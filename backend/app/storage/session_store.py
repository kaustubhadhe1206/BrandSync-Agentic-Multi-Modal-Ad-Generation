"""Session store. In-memory for live access, mirrored to Supabase Postgres
so a session survives a backend restart — e.g. Render's free tier sleeping
after 15 min idle, which wipes the local filesystem entirely (confirmed: a
local SQLite file would NOT have survived that, same reason artifact files
moved to Supabase Storage instead of local disk).

Opt-in, same pattern as storage/cloud_cache.py: with no SUPABASE_URL/KEY
configured, every persistence call is a no-op and this behaves exactly like
the original pure-in-memory store (so local dev without credentials keeps
working unchanged).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..config import settings

_TABLE = "sessions"


@dataclass
class SessionEvent:
    """A single event emitted during agent execution, sent to the frontend via SSE."""
    timestamp: float
    agent: str          # 'strategist' | 'creative_director' | 'post_production' | 'supervisor' | 'system'
    kind: str           # 'thinking' | 'tool_call' | 'tool_result' | 'message' | 'handoff' | 'error' | 'done'
    text: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "agent": self.agent, "kind": self.kind, "text": self.text, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionEvent":
        return cls(
            timestamp=d["timestamp"], agent=d["agent"], kind=d["kind"],
            text=d["text"], data=d.get("data") or {},
        )


@dataclass
class Session:
    id: str
    created_at: float = field(default_factory=time.time)
    state: dict[str, Any] = field(default_factory=dict)
    events: list[SessionEvent] = field(default_factory=list)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    finished: bool = False
    error: str | None = None
    # Set by SessionStore on create/load. Excluded from repr/eq — a Lock and
    # a bound method aren't meaningfully representable or comparable.
    _on_change: Callable[["Session"], Awaitable[None]] | None = field(default=None, repr=False, compare=False)
    _persist_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    async def emit(self, agent: str, kind: str, text: str, **data: Any) -> None:
        ev = SessionEvent(timestamp=time.time(), agent=agent, kind=kind, text=text, data=data)
        self.events.append(ev)
        await self.event_queue.put(ev)
        if self._on_change:
            await self._on_change(self)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._client = None
        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            try:
                from supabase import create_client

                self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            except Exception:
                self._client = None

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def create(self) -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid)
        s.state["session_id"] = sid
        s._on_change = self._persist
        self._sessions[sid] = s
        # Fire-and-forget — /generate must return session_id immediately;
        # the very next emit() will persist anyway if this is slow/fails.
        asyncio.create_task(self._persist(s))
        return s

    async def get(self, sid: str) -> Session | None:
        s = self._sessions.get(sid)
        if s:
            return s
        # Not in this process's memory — e.g. it restarted. Try Supabase
        # before giving up; a hit here is what makes a session survive a
        # sleep/wake cycle instead of 404ing like an in-memory-only store.
        s = await self._load(sid)
        if s:
            s._on_change = self._persist
            self._sessions[sid] = s
        return s

    async def _persist(self, session: Session) -> None:
        if not self.is_configured:
            return
        async with session._persist_lock:  # never let two writes race out of order
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._persist_sync, session), timeout=10
                )
            except Exception:
                pass  # best-effort recovery data, never block/break a live session over it

    def _persist_sync(self, session: Session) -> None:
        self._client.table(_TABLE).upsert(
            {
                "id": session.id,
                "created_at": session.created_at,
                "state": session.state,
                "events": [e.to_dict() for e in session.events],
                "finished": session.finished,
                "error": session.error,
            },
            on_conflict="id",
        ).execute()

    async def _load(self, sid: str) -> Session | None:
        if not self.is_configured:
            return None
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._load_sync, sid), timeout=10)
        except Exception:
            return None

    def _load_sync(self, sid: str) -> Session | None:
        res = self._client.table(_TABLE).select("*").eq("id", sid).maybe_single().execute()
        if not res or not res.data:
            return None
        row = res.data
        return Session(
            id=row["id"],
            created_at=row["created_at"],
            state=row.get("state") or {},
            events=[SessionEvent.from_dict(e) for e in (row.get("events") or [])],
            finished=row.get("finished", False),
            error=row.get("error"),
        )


store = SessionStore()
