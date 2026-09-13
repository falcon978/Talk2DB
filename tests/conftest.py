import pytest
import asyncio
from unittest.mock import AsyncMock

from talk2db.state import AgentState
from talk2db.db_executor import DBExecutor

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_db_executor():
    """Provide a mocked DBExecutor."""
    mock = AsyncMock(spec=DBExecutor)
    return mock

@pytest.fixture
def mock_state():
    """Provide a default AgentState."""
    return AgentState(
        session_id="test_session",
        recent_messages=[],
        filters={}
    )
