from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class SessionStore(ABC):
    """Manages conversation sesissions and message history.
    Each session belongs to one project (Project ID) and accumulates history of user/assistant messages.
    """
    
    @abstractmethod
    async def create_session(self, proj_id: str) -> Dict[str, Any]:
        """Create a new session for a project.
        Returns:
            {"session_id": str, "proj_id": str}"""
        ...
    
    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch sesisson metadata 
        Returns:
            {"session_id": str, "proj_id": str, "summary": str, ...}
            or None if session does not exist.
        """
        ...

    @abstractmethod
    async def append_message(self, session_id: str, role: str, content: str) -> None:
        """Append a single message to the session history.
        
        Args:
            session_id: Target session.
            role: 'user' or 'assistant'
            content: Message text
        """
        ...

    @abstractmethod
    async def get_recent_messages(self, session_id: str, limit: int = 12) -> List[Dict[str, str]]:
        """Fetch the N most recent messages, newest-first, then reversed to chronological order for LLM context."""
        ...

    @abstractmethod
    async def get_summary(self, session_id: str) -> str:
        """Fetch the compressed semantic summary of earlier conversation history."""
        ...

    @abstractmethod
    async def update_summary(self, session_id: str, summary: str) -> None:
        """Store/overwrite the conversation summary for this session."""
        ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Hard-delete a session and all its messages."""
        ...


class QueryCache(ABC):
    """Caches analytics tool results keyed by a (proj_id, intent, params fingerprint).
    Cache keys are content-addressed - two semantically identical queries 
    (different wording, same intent + params) hit the same cache entry.
    """

    @abstractmethod
    async def get(self, proj_id: str, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Fetch a cached result by project and query fingerprint.
        Returns the cached tool result dict, or None if no cache entry exists."""
        ... 

    @abstractmethod
    async def set(self, proj_id: str, fingerprint: str, result: Dict[str, Any], ttl_second:int = 86400) -> None:
        """Store a tool result in the cache under the given project and query fingerprint."""
        ...
    

    @abstractmethod
    async def invalidate_project(self, proj_id: str) -> None:
        """Invalidate all cache entries for a project, e.g. when data sources are updated."""
        ...

    @abstractmethod
    async def invalidate_entry(self, proj_id: str, fingerprint: str) -> None:
        """Invalidate a single cache entry."""
        ...