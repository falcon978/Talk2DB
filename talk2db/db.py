"""
Database pool factories and chat history persistence.

Pool factories are low-level builders used by lifecycle.py (NOT called per-request).
Chat history functions handle audit logging and session retrieval for the UI.
"""

import json

import asyncpg
from psycopg_pool import AsyncConnectionPool

from talk2db.config import settings
from talk2db.logger import get_logger

logger = get_logger(__name__)


async def create_app_pool() -> AsyncConnectionPool:
    """
    Creates a psycopg AsyncConnectionPool with full permissions.
    Used exclusively for LangGraph Checkpoints which strictly require psycopg.
    """
    pool = AsyncConnectionPool(
        conninfo=settings.db_dsn_app,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"autocommit": True}
    )
    await pool.open()
    return pool


async def create_target_pool() -> asyncpg.Pool:
    """
    Creates a read-only asyncpg pool.
    Used strictly by the DBExecutor for LLM-generated SQL queries.
    """
    return await asyncpg.create_pool(
        settings.db_dsn_target, min_size=2, max_size=10
    )


async def log_chat_history(pool: AsyncConnectionPool, session_id: str, turn_number: int, user_query: str, state: dict, latency_ms: int = 0):
    """
    Logs the conversational turn into the chat_history analytics table.
    Must use the app_pool (psycopg) because the target_pool is read-only.
    """
    query = """
        INSERT INTO chat_history (
            session_id, turn_number, user_query, operation, 
            generated_sql, model_response, execution_status, 
            retry_count, error_message, latency_ms, token_count
        ) VALUES (
            %(session_id)s, %(turn_number)s, %(user_query)s, %(operation)s, 
            %(generated_sql)s, %(model_response)s, %(execution_status)s, 
            %(retry_count)s, %(error_message)s, %(latency_ms)s, %(token_count)s
        )
        ON CONFLICT (session_id, turn_number) DO NOTHING;
    """
    
    op = state.get("operation")
    op_val = op.value if hasattr(op, "value") else op
    
    # Determine execution status from the final state
    status = "SUCCESS"
    if state.get("last_error"):
        status = "ERROR"
    elif op_val == "REFUSE":
        status = "REFUSED"

    # Extract the last assistant message from recent_messages
    recent_msgs = state.get("recent_messages", [])
    model_response = recent_msgs[-1].content if recent_msgs and hasattr(recent_msgs[-1], 'content') else None
        
    params = {
        "session_id": session_id,
        "turn_number": turn_number,
        "user_query": user_query,
        "operation": op_val,
        "generated_sql": state.get("last_sql"),
        "model_response": model_response,
        "execution_status": status,
        "retry_count": state.get("retry_count", 0),
        "error_message": state.get("last_error"),
        "latency_ms": latency_ms,
        "token_count": state.get("token_count", 0)
    }
    
    try:
        async with pool.connection() as conn:
            await conn.execute(query, params)
    except Exception as e:
        logger.error(f"Failed to log chat history: {e}")

async def get_recent_sessions(pool: AsyncConnectionPool) -> dict[str, str]:
    """
    Fetches the 20 most recent unique session IDs from chat_history,
    returning a dictionary mapping session_id to a human-readable label.
    """
    query = """
        SELECT 
            session_id, 
            MAX(created_at) as last_active,
            (SELECT user_query FROM chat_history h2 WHERE h2.session_id = chat_history.session_id ORDER BY turn_number ASC LIMIT 1) as first_query
        FROM chat_history 
        GROUP BY session_id 
        ORDER BY last_active DESC 
        LIMIT 20;
    """
    try:
        async with pool.connection() as conn:
            records = await conn.execute(query)
            results = await records.fetchall()
            
            session_dict = {}
            for row in results:
                sid = str(row[0])
                # Format: "Aug 30, 14:30 - Show me active farmers..."
                timestamp_str = row[1].strftime("%b %d, %H:%M") if row[1] else "Unknown"
                query_snippet = row[2] or "Empty Session"
                if len(query_snippet) > 35:
                    query_snippet = query_snippet[:32] + "..."
                
                session_dict[sid] = f"{timestamp_str} - {query_snippet}"
                
            return session_dict
    except Exception as e:
        logger.error(f"Failed to fetch recent sessions: {e}")
        return {}

async def get_session_messages(pool: AsyncConnectionPool, session_id: str) -> list[dict]:
    """
    Fetches the complete turn history for a given session.
    Reconstructs the Streamlit-compatible message format for UI hydration.
    """
    query = """
        SELECT user_query, model_response, generated_sql 
        FROM chat_history 
        WHERE session_id = %(session_id)s 
        ORDER BY turn_number ASC;
    """
    try:
        async with pool.connection() as conn:
            records = await conn.execute(query, {"session_id": session_id})
            results = await records.fetchall()
            
            messages = []
            for row in results:
                # row is (user_query, model_response, generated_sql)
                messages.append({"role": "user", "content": row[0]})
                
                ast_msg = {"role": "assistant", "content": row[1] or "Query successful."}
                if row[2]:
                    ast_msg["sql"] = row[2]
                messages.append(ast_msg)
                
            return messages
    except Exception as e:
        logger.error(f"Failed to fetch session messages: {e}")
        return []

async def log_system_error(pool: AsyncConnectionPool, session_id: str, error_message: str, stack_trace: str):
    """
    Logs internal system crashes and UI exceptions to the system_errors table.
    """
    query = """
        INSERT INTO system_errors (session_id, error_message, stack_trace)
        VALUES (%(session_id)s, %(error_message)s, %(stack_trace)s)
    """
    try:
        async with pool.connection() as conn:
            await conn.execute(query, {
                "session_id": session_id,
                "error_message": error_message,
                "stack_trace": stack_trace
            })
    except Exception as e:
        logger.error(f"Failed to log system error: {e}")
