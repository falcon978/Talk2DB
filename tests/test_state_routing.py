import pytest
from talk2db.state import AgentState, Operation
from talk2db.schemas import RoutingOutput

def test_routing_output_defaults():
    ro = RoutingOutput(operation=Operation.NEW, reasoning="test reasoning")
    assert ro.topic == ""
    assert ro.filters == {}
    assert ro.group_by == []
    assert ro.referenced_entities == []

def test_agent_state_initialization():
    state = AgentState(
        session_id="test_123",
        recent_messages=[],
        filters={"district": "Pune"}
    )
    assert state.session_id == "test_123"
    assert state.filters == {"district": "Pune"}
    assert state.retry_count == 0
    assert state.last_error is None

