import pytest
from langchain_core.messages import HumanMessage, AIMessage
from talk2db.nodes import clarification_node, refusal_node
from talk2db.state import AgentState, Operation

@pytest.mark.asyncio
async def test_clarification_node():
    """Test that the clarification node appends an AIMessage and signals pending clarification."""
    state = AgentState(
        session_id="test_session",
        recent_messages=[HumanMessage(content="What about the other thing?")],
        operation=Operation.CLARIFY,
        filters={}
    )
    
    output = await clarification_node(state)
    
    assert output["pending_clarification"] is True
    assert "recent_messages" in output
    assert len(output["recent_messages"]) == 1
    assert isinstance(output["recent_messages"][0], AIMessage)
    assert "specific details" in output["recent_messages"][0].content.lower()

@pytest.mark.asyncio
async def test_refusal_node():
    """Test that the refusal node appends an AIMessage refusing out-of-schema queries."""
    state = AgentState(
        session_id="test_session",
        recent_messages=[HumanMessage(content="What is the weather today?")],
        operation=Operation.REFUSE,
        filters={}
    )
    
    output = await refusal_node(state)
    
    assert output.get("pending_clarification") in [None, False]
    assert "recent_messages" in output
    assert len(output["recent_messages"]) == 1
    assert isinstance(output["recent_messages"][0], AIMessage)
    assert "sorry" in output["recent_messages"][0].content.lower()
