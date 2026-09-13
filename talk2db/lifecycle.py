"""
Application lifecycle manager for database pools and the compiled LangGraph agent.

Decoupled from any specific frontend (Streamlit, FastAPI, CLI).
Any entrypoint imports this module and calls `startup()` / `shutdown()`.
"""

import asyncio

from talk2db.db import create_app_pool, create_target_pool
from talk2db.graph import compile_agent_with_postgres
from talk2db.llm import get_llm
from talk2db.db_executor import DBExecutor
from talk2db.logger import get_logger
from talk2db.exceptions import ResourceInitializationError

logger = get_logger(__name__)


class AppContext:
    """
    Holds all shared, long-lived resources for the application.
    Initialized once at startup, reused across every request.
    """

    def __init__(self):
        self.app_pool = None
        self.target_pool = None
        self.graph = None
        self.llm = None
        self.db_executor: DBExecutor | None = None


_ctx = AppContext()


async def startup() -> AppContext:
    """
    Initializes all shared resources exactly once.
    Must be called before the first request in any entrypoint (Streamlit, FastAPI, CLI).
    """
    if _ctx.graph is not None:
        logger.debug("Application context already initialized, skipping startup.")
        return _ctx  # Already initialized

    logger.info("Initializing backend resources...")
    try:
        # 1. psycopg pool for LangGraph Checkpoints (requires psycopg, not asyncpg)
        logger.info("Creating App DB Pool (psycopg)...")
        _ctx.app_pool = await create_app_pool()

        # 2. asyncpg pool for read-only SQL execution
        logger.info("Creating Target DB Pool (asyncpg)...")
        _ctx.target_pool = await create_target_pool()

        # 3. Wrap the agri pool in the DBExecutor (SOLID dependency injection target)
        _ctx.db_executor = DBExecutor(_ctx.target_pool)

        # 4. Compile the LangGraph agent with Postgres checkpointer (runs setup/migration once)
        logger.info("Compiling LangGraph agent and checkpointer...")
        _ctx.graph = await compile_agent_with_postgres(_ctx.app_pool)

        # 5. Instantiate the LLM client once
        logger.info("Initializing LLM client...")
        _ctx.llm = get_llm()

        logger.info("Backend initialization complete.")
        return _ctx
    except Exception as e:
        logger.exception("Failed to initialize backend resources.")
        raise ResourceInitializationError(f"Backend startup failed: {e}") from e


async def shutdown() -> None:
    """Gracefully closes all shared resources."""
    logger.info("Shutting down backend resources...")
    try:
        if _ctx.target_pool:
            await _ctx.target_pool.close()
            logger.info("Closed Target DB Pool.")
        if _ctx.app_pool:
            await _ctx.app_pool.close()
            logger.info("Closed App DB Pool.")
    except Exception as e:
        logger.exception("Error during resource shutdown.")


def get_context() -> AppContext:
    """Returns the initialized application context. Raises if startup() was not called."""
    if _ctx.graph is None:
        raise RuntimeError("Application context not initialized. Call startup() first.")
    return _ctx
