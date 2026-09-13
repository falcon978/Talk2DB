from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
import asyncio
import time

import traceback

from talk2db.lifecycle import startup, shutdown, get_context
from talk2db.db import get_recent_sessions, get_session_messages, log_chat_history, log_system_error
from talk2db.cache import ActiveSessionCache
from talk2db.callbacks import TokenCounterCallback
from talk2db.logger import get_logger

logger = get_logger(__name__)
cache = ActiveSessionCache()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting FastAPI backend...")
    await startup()
    await cache.ping()
    yield
    # Shutdown
    logger.info("Shutting down FastAPI backend...")
    await shutdown()

from config import config
app = FastAPI(title=config.api_title, lifespan=lifespan)

class ChatRequest(BaseModel):
    session_id: str
    user_message: str
    turn_number: int

@app.get("/sessions")
async def get_sessions():
    ctx = get_context()
    return await get_recent_sessions(ctx.app_pool)

@app.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    ctx = get_context()
    return await get_session_messages(ctx.app_pool, session_id)


@app.get("/sessions/{session_id}/state")
async def get_state(session_id: str):
    state = await cache.get_session(session_id)
    return state or {}

@app.post("/chat")
async def chat(req: ChatRequest):
    ctx = get_context()
    token_counter = TokenCounterCallback()

    config = {
        "configurable": {
            "thread_id": req.session_id,
            "db_executor": ctx.db_executor,
            "llm": ctx.llm
        },
        "callbacks": [token_counter]
    }

    inputs = {
        "session_id": req.session_id,
        "recent_messages": [HumanMessage(content=req.user_message)]
    }

    try:
        start_time = time.monotonic()
        final_state = await ctx.graph.ainvoke(inputs, config)
        latency_ms = int((time.monotonic() - start_time) * 1000)
    except Exception as e:
        logger.exception("Graph execution failed")
        asyncio.create_task(
            log_system_error(ctx.app_pool, req.session_id, str(e), traceback.format_exc())
        )
        raise HTTPException(status_code=500, detail="Internal System Error")

    final_state["token_count"] = token_counter.total_tokens

    # Update Redis Cache with the new derived projection
    await cache.set_session(req.session_id, final_state)

    # Fire and forget: log the turn to Postgres analytics table
    asyncio.create_task(
        log_chat_history(
            ctx.app_pool,
            req.session_id,
            req.turn_number,
            req.user_message,
            final_state,
            latency_ms
        )
    )

    # Prepare response, stripping out non-serializable Langchain messages
    response = {
        "pending_clarification": final_state.get("pending_clarification"),
        "operation": final_state.get("operation") or final_state.get("intent"),
        "last_error": final_state.get("last_error"),
        "last_sql": final_state.get("last_sql"),
        "last_row_count": final_state.get("last_row_count") or 0,
        "last_result_sample": final_state.get("last_result_sample"),
        "retry_count": final_state.get("retry_count") or 0,
        "token_count": final_state.get("token_count") or 0,
    }
    return response
