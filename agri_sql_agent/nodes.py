"""
LangGraph node implementations for the Conversational Text-to-SQL Agent.

Each node is an async function that receives the current AgentState and a RunnableConfig,
performs its logic, and returns a dictionary of state updates.
"""

import os
from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, AIMessage
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel, Field

from agri_sql_agent.state import AgentState, Operation
from agri_sql_agent.schemas import RoutingOutput, SQLOutput
from agri_sql_agent.guardrails import validate_and_format_sql
from agri_sql_agent.exceptions import SQLSecurityViolation, DatabaseExecutionError, LLMGenerationError, ResourceInitializationError
from agri_sql_agent.logger import get_logger
from agri_sql_agent.config import settings

logger = get_logger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(filename: str) -> str:
    """Loads a prompt template from the prompts directory."""
    with open(os.path.join(PROMPTS_DIR, filename), "r") as f:
        return f.read()

SCHEMA_PROMPT = load_prompt("schema.txt")
ROUTER_PROMPT = load_prompt("router.txt")
SQL_GEN_PROMPT = load_prompt("sql_gen.txt")


# --- Node Implementations ---

async def router_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Analyzes the latest user message to determine the semantic operation.

    Args:
        state: Current AgentState containing message history.
        config: RunnableConfig containing the injected LLM client.

    Returns:
        Dict containing state updates (operation, topic, filters, group_by, referenced_entities, last_error).

    Failure Modes:
        - ResourceInitializationError: Raised if the LLM client is missing from config.
        - Fallback: Returns Operation.CLARIFY and a last_error string if structured parsing fails.
    """
    llm = config["configurable"].get("llm")
    if not llm:
        raise ResourceInitializationError("LLM client not found in config.")

    messages = state.recent_messages
    last_user_message = messages[-1].content if messages else ""
    history = "\n".join(
        [f"{m.type}: {m.content}" for m in messages[:-1][-settings.context_window_turns:]]
    ) if len(messages) > 1 else "No previous history."

    logger.info(f"Routing new user query: '{last_user_message[:50]}...'")

    prompt = ROUTER_PROMPT.format(history=history, user_query=last_user_message, schema=SCHEMA_PROMPT)

    try:
        router = llm.with_structured_output(RoutingOutput)
        result = await router.ainvoke([SystemMessage(content=prompt)])
        logger.info(f"Router classified operation as: {result.operation.value if hasattr(result.operation, 'value') else result.operation}")
        logger.info(f"Router Reasoning: {result.reasoning}")
    except Exception as e:
        logger.exception("Router failed to parse LLM structured output.")
        return {
            "operation": Operation.CLARIFY,
            "last_error": f"Router parsing failed: {str(e)}"
        }

    op = result.operation
    updates: Dict[str, Any] = {
        "operation": op,
        "topic": result.topic,
        "filters": result.filters,
        "group_by": result.group_by,
        "referenced_entities": result.referenced_entities,
        "last_error": None
    }

    # State Retention & Reset Rules
    updates["pending_clarification"] = False
    
    if op == Operation.NEW:
        updates["last_sql"] = None
        updates["last_result_schema"] = None
        updates["retry_count"] = 0
    elif op == Operation.CLARIFY:
        updates["pending_clarification"] = True

    return updates


async def sql_gen_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Generates a PostgreSQL query using the bounded semantic context.

    Args:
        state: Current AgentState containing schema elements, previous SQL, and error feedback.
        config: RunnableConfig containing the injected LLM client.

    Returns:
        Dict containing state updates (last_sql, last_error).

    Failure Modes:
        - ResourceInitializationError: Raised if the LLM client is missing from config.
        - Fallback: Increments retry_count and returns last_error string if structured parsing fails.
    """
    llm = config["configurable"].get("llm")
    if not llm:
        raise ResourceInitializationError("LLM client not found in config.")

    if state.operation == Operation.NEW:
        history = f"User: {state.recent_messages[-1].content}"
    else:
        history = "\n".join([f"{m.type}: {m.content}" for m in state.recent_messages[-settings.context_window_turns:]])
    logger.info("Generating SQL query for semantic context.")

    prompt = SQL_GEN_PROMPT.format(
        schema_ddl=SCHEMA_PROMPT,
        topic=state.topic or 'None',
        filters=state.filters or 'None',
        group_by=state.group_by or 'None',
        entities=state.referenced_entities or 'None',
        history=history,
        previous_sql=state.last_sql or 'None',
        previous_error=state.last_error or 'None'
    )

    try:
        sql_generator = llm.with_structured_output(SQLOutput)
        result = await sql_generator.ainvoke([SystemMessage(content=prompt)])
        logger.info("SQL query generated successfully.")
        logger.info(f"SQL Reasoning: {result.reasoning}")
        logger.debug(f"Generated SQL: {result.sql}")
        return {"last_sql": result.sql, "last_error": None}
    except Exception as e:
        logger.exception("SQL Generation failed due to LLM parsing error.")
        return {
            "last_error": f"SQL Generation failed: {str(e)}",
            "retry_count": state.retry_count + 1
        }


async def validator_node(state: AgentState) -> Dict[str, Any]:
    """
    Validates the generated SQL using sqlglot guardrails safely at the AST level.

    Args:
        state: Current AgentState containing last_sql.

    Returns:
        Dict containing state updates (last_sql, last_error).

    Failure Modes:
        - SQLSecurityViolation: Caught and returned as last_error, incrementing retry_count.
    """
    sql = state.last_sql
    if not sql:
        logger.warning("Validator received empty SQL.")
        return {"last_error": "No SQL generated.", "retry_count": state.retry_count + 1}

    logger.info("Running guardrails AST validation on generated SQL.")
    try:
        validated_sql = validate_and_format_sql(sql)
        return {"last_sql": validated_sql, "last_error": None}
    except SQLSecurityViolation as e:
        logger.warning(f"SQL validation failed: {str(e)}")
        return {"last_error": str(e), "retry_count": state.retry_count + 1}


async def executor_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Executes the validated SQL against the read-only Agricultural pool.

    Args:
        state: Current AgentState containing last_sql.
        config: RunnableConfig containing the injected DBExecutor.

    Returns:
        Dict containing state updates (last_result_sample, last_result_schema, last_row_count, last_error).

    Failure Modes:
        - ResourceInitializationError: Raised if DBExecutor is missing from config.
        - DatabaseExecutionError: Caught and returned as last_error, incrementing retry_count.
    """
    db_executor = config["configurable"].get("db_executor")
    if not db_executor:
        raise ResourceInitializationError("DBExecutor not found in config.")

    logger.info("Executing validated SQL against PostgreSQL.")
    try:
        records = await db_executor.execute_query(state.last_sql)
        records = records or []
        
        # Limits the returned dataset sample to prevent state bloat.
        sample = records[:settings.result_row_limit]
        row_count = len(records)
        schema_keys = list(records[0].keys()) if row_count > 0 else []
        
        logger.info(f"Execution completed. Row count: {row_count}")
        return {
            "last_result_sample": sample,
            "last_result_schema": ", ".join(schema_keys),
            "last_row_count": row_count,
            "last_error": None
        }
    except DatabaseExecutionError as e:
        logger.error(f"Executor node caught DatabaseExecutionError: {str(e)}")
        return {"last_error": str(e), "retry_count": state.retry_count + 1}


async def clarification_node(state: AgentState) -> Dict[str, Any]:
    """
    Handles ambiguous queries by returning a clarification prompt.

    Args:
        state: Current AgentState.

    Returns:
        Dict containing state updates (recent_messages, pending_clarification=True).
    """
    msg = AIMessage(
        content="Could you please provide more specific details? "
                "For example, which district or season are you interested in?"
    )
    return {"recent_messages": [msg], "pending_clarification": True}


async def refusal_node(state: AgentState) -> Dict[str, Any]:
    """
    Gracefully refuses out-of-schema questions.

    Args:
        state: Current AgentState.

    Returns:
        Dict containing state updates (recent_messages).
    """
    msg = AIMessage(
        content="I'm sorry, but I can only answer questions related to the agricultural "
                "database schema (farmers, plots, crops, sensors, etc.)."
    )
    return {"recent_messages": [msg]}
