"""
Defines the Pydantic schemas for the AgentState and conversational routing logic.
"""

from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, Sequence
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class Operation(str, Enum):
    NEW = "NEW"
    REFINE = "REFINE"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"

def manage_messages(existing: Sequence[BaseMessage], new: Sequence[BaseMessage]) -> list[BaseMessage]:
    """
    Custom reducer for the `recent_messages` state field.
    Appends new messages and enforces a strict bounding box of the last 8 messages (4 turns).
    """
    # Use LangGraph's robust add_messages to handle deduplication and merging
    merged = add_messages(existing, new)
    
    # Bound to at most 4 turns (a turn is usually 2 messages: user + assistant, so 8 messages total)
    if len(merged) > 8:
        return merged[-8:]
    return merged

class AgentState(BaseModel):
    """
    Semantic State and Execution State for the LangGraph agent.
    Strictly isolates semantic tracking from raw chat history.
    """
    # Session Context
    session_id: str
    
    # Semantic Context
    topic: Optional[str] = None
    operation: Optional[Operation] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    group_by: List[str] = Field(default_factory=list)
    referenced_entities: List[str] = Field(default_factory=list)
    
    # Execution Context
    last_sql: Optional[str] = None
    last_result_schema: Optional[str] = None
    last_result_sample: Optional[List[Dict[str, Any]]] = None
    last_row_count: Optional[int] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    
    # Clarification Context
    pending_clarification: bool = False
    
    # Bounded Conversational Context
    recent_messages: Annotated[list[BaseMessage], manage_messages] = Field(default_factory=list)
