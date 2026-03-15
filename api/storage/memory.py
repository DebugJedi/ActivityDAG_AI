from __future__ import annotations
import hashlib
import time
import uuid
from collections import defaultdict
from typing import Dict, Any, Optional

from .base import QueryCache, SessionStore


class InMemorySessionStore(SessionStore):
    def __init__(self, max_history: int = 100):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.messages: Dict[str, list[Dict[str, str]]] = defaultdict(list)
        self.max_history = max_history

    async def create_session(self, proj_id: str) -> Dict[str, Any]:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = {
            "id": session_id,
            "project_id": str(proj_id),
            "summary": "",
            "created_at": time.time(),
        }
        self._message[session_id] = []
        return {"session_id": session_id, "proj_id": str(proj_id)}
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)
    