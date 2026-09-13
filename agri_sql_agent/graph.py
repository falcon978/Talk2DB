"""
Defines the LangGraph StateGraph, compiling nodes and routing edges.
"""

from typing import Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from agri_sql_agent.config import settings

from agri_sql_agent.state import AgentState, Operation
from agri_sql_agent.nodes import (
    router_node, sql_gen_node, validator_node, 
    executor_node, clarification_node, refusal_node
)
from agri_sql_agent.logger import get_logger

logger = get_logger(__name__)

def route_after_router(state: AgentState) -> Literal["clarify", "refuse", "sql_gen"]:
    """Routes execution after the intent router, catching router failures."""
    if state.last_error:
        logger.warning(f"Routing fallback to 'clarify' due to error: {state.last_error}")
        return "clarify"  # Graceful fallback if routing structured output completely failed
        
    if state.operation == Operation.CLARIFY:
        return "clarify"
    elif state.operation == Operation.REFUSE:
        return "refuse"
    return "sql_gen"

def _create_retry_router(success_node: str, step_name: str):
    """Factory to create a router that retries on failure or proceeds to the success node."""
    def route(state: AgentState) -> Literal["sql_gen", "clarify", "executor", "validator", "__end__"]:
        if state.last_error:
            if state.retry_count < settings.max_retries:
                logger.info(f"Retrying SQL generation after {step_name} failure (attempt {state.retry_count + 1})")
                return "sql_gen"
            else:
                logger.warning(f"Max retries reached after {step_name}. Ending graph with error.")
                return "__end__"
        return success_node
    return route

def build_graph() -> StateGraph:
    """Constructs the LangGraph StateGraph mapping nodes and edges."""
    builder = StateGraph(AgentState)
    
    # Add nodes
    builder.add_node("router", router_node)
    builder.add_node("sql_gen", sql_gen_node)
    builder.add_node("validator", validator_node)
    builder.add_node("executor", executor_node)
    builder.add_node("clarify", clarification_node)
    builder.add_node("refuse", refusal_node)
    
    # Add edges
    builder.set_entry_point("router")
    
    builder.add_conditional_edges(
        "router", 
        route_after_router, 
        {"clarify": "clarify", "refuse": "refuse", "sql_gen": "sql_gen"}
    )
    
    builder.add_conditional_edges(
        "sql_gen",
        _create_retry_router("validator", "generation"),
        {"sql_gen": "sql_gen", "clarify": "clarify", "validator": "validator"}
    )
    
    builder.add_conditional_edges(
        "validator",
        _create_retry_router("executor", "validation"),
        {"sql_gen": "sql_gen", "clarify": "clarify", "executor": "executor"}
    )
    
    builder.add_conditional_edges(
        "executor",
        _create_retry_router(END, "execution"),
        {"sql_gen": "sql_gen", "clarify": "clarify", END: END}
    )
    
    builder.add_edge("clarify", END)
    builder.add_edge("refuse", END)
    
    return builder

async def compile_agent_with_postgres(pool: AsyncConnectionPool):
    """
    Initializes the Postgres checkpointer, runs its setup, and compiles the graph.
    The pool passed here MUST be the App/State pool with DDL permissions.
    """
    logger.info("Initializing Postgres checkpointer for LangGraph...")
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()  # Dynamically bootstraps the checkpoint tables
    
    logger.info("Compiling LangGraph StateGraph...")
    builder = build_graph()
    app = builder.compile(checkpointer=checkpointer)
    logger.info("LangGraph compilation complete.")
    return app
