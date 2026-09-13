"""
Defines the Pydantic schemas for structured LLM generation.
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field
from talk2db.state import Operation

class RoutingOutput(BaseModel):
    """Pydantic model representing the parsed intent router output."""
    reasoning: str = Field(description="Step-by-step chain of thought explaining the semantic classification.")
    operation: Operation = Field(description="The classified operation type based on the user's latest query.")
    topic: str = Field(description="The semantic topic of the conversation.", default="")
    filters: Dict[str, Any] = Field(description="Dictionary of filters mentioned (e.g., district, season).", default_factory=dict)
    group_by: List[str] = Field(description="List of grouping criteria mentioned.", default_factory=list)
    referenced_entities: List[str] = Field(description="List of specific entities referenced.", default_factory=list)

class SQLOutput(BaseModel):
    """Pydantic model representing the parsed generated SQL query."""
    reasoning: str = Field(description="Step-by-step chain of thought detailing table joins, filtering, and aggregation logic.")
    sql: str = Field(description="The generated PostgreSQL SELECT query.")
