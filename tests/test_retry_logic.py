import pytest
from unittest.mock import AsyncMock, MagicMock
from talk2db.nodes import executor_node
from talk2db.state import AgentState
from talk2db.exceptions import DatabaseExecutionError

@pytest.mark.asyncio
async def test_executor_node_catches_db_error_and_increments_retry():
    # Setup mock state
    state = AgentState(
        session_id="test",
        last_sql="SELECT * FROM does_not_exist",
        retry_count=1
    )
    
    # Setup mock DBExecutor
    mock_db_executor = AsyncMock()
    mock_db_executor.execute_query.side_effect = DatabaseExecutionError("Relation does not exist")
    
    config = {
        "configurable": {
            "db_executor": mock_db_executor
        }
    }
    
    # Run node
    result = await executor_node(state, config)
    
    # Assertions
    assert "last_error" in result
    assert "Relation does not exist" in result["last_error"]
    assert result["retry_count"] == 2 # Incremented from 1
