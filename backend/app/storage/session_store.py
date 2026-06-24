"""In-memory session store. Holds per-session state and event queue for SSE.

Production swap-in: this would be Redis or a database. For a portfolio project
that runs single-instance, in-memory is fine and keeps the dep count low.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionEvent:
    """A single event emitted during agent execution, sent to the frontend via SSE."""
    timestamp: float
    agent: str          # 'strategist' | 'creative_director' | 'post_production' | 'supervisor' | 'system'
    kind: str           # 'thinking' | 'tool_call' | 'tool_result' | 'message' | 'handoff' | 'error' | 'done'
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    id: str
    created_at: float = field(default_factory=time.time)
    state: dict[str, Any] = field(default_factory=dict)
    events: list[SessionEvent] = field(default_factory=list)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    finished: bool = False
    error: str | None = None

    async def emit(self, agent: str, kind: str, text: str, **data: Any) -> None:
        ev = SessionEvent(timestamp=time.time(), agent=agent, kind=kind, text=text, data=data)
        self.events.append(ev)
        await self.event_queue.put(ev)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid)
        s.state["session_id"] = sid
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)


store = SessionStore()
