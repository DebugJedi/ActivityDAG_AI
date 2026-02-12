from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import uuid
from .config import MAX_HISTORY_MESSAGES

@dataclass
class Session:
    id: str
    proj_id: str
    history: List[Dict[str, str]] = field(default_factory=list)

class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    def create(self, proj_id: str) -> Session:
        sid = uuid.uuid4().hex
        s = Session(id=sid, proj_id=str(proj_id))
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Optional[Session]:
        return self._sessions.get(sid)

    def append(self, sid: str, role: str, content: str) -> None:
        s = self._sessions.get(sid)
        if not s:
            return
        s.history.append({"role": role, "content": content})
        # trim
        if len(s.history) > MAX_HISTORY_MESSAGES * 2:
            s.history = s.history[-MAX_HISTORY_MESSAGES * 2:]
