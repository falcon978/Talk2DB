"""
Non-authoritative Redis cache for active LangGraph session context.

Stores only a derived projection of the active state to serve the UI quickly.
On Redis failure, the system gracefully degrades — the UI simply won't show
cached sidebar data until the next successful graph execution repopulates it.
"""

import json
from typing import Dict, Any, Optional

import redis.asyncio as aioredis

from talk2db.config import settings
from talk2db.logger import get_logger

logger = get_logger(__name__)


class ActiveSessionCache:
    """
    Non-authoritative async Redis cache for active LangGraph session context.
    Stores only a derived projection of the active state to serve the UI quickly.
    """

    def __init__(self, url: str = settings.redis_url):
        """Connects to Redis asynchronously. Gracefully degrades if Redis is unavailable."""
        try:
            self.client = aioredis.from_url(url, decode_responses=True)
            self._available = True
        except Exception:
            logger.warning("Redis client creation failed. Active session cache will be disabled.")
            self.client = None
            self._available = False

    async def ping(self) -> bool:
        """Validates the Redis connection. Disables cache on failure."""
        if not self._available:
            return False
        try:
            await self.client.ping()
            return True
        except Exception:
            logger.warning("Redis is unavailable. Active session cache will be disabled.")
            self._available = False
            return False

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetches the active semantic context from Redis. Returns None on miss or failure."""
        if not self._available:
            return None
        try:
            data = await self.client.get(f"session:{session_id}")
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Redis read error: {e}")
        return None

    async def set_session(self, session_id: str, state_dict: Dict[str, Any], ttl_seconds: int = settings.cache_ttl_seconds):
        """
        Stores a serialized projection of the state.
        Only stores execution/semantic state, NOT raw messages.
        """
        if not self._available:
            return

        try:
            operation = state_dict.get("operation")
            safe_state = {
                "session_id": session_id,
                "topic": state_dict.get("topic"),
                "operation": operation.value if hasattr(operation, 'value') else operation,
                "filters": state_dict.get("filters", {}),
                "last_sql": state_dict.get("last_sql"),
                "last_row_count": state_dict.get("last_row_count"),
                "last_error": state_dict.get("last_error"),
                "pending_clarification": state_dict.get("pending_clarification", False)
            }
            await self.client.setex(
                f"session:{session_id}", ttl_seconds, json.dumps(safe_state)
            )
        except Exception as e:
            logger.warning(f"Redis write error: {e}")
