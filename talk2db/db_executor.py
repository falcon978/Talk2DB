"""
Secure SQL execution wrapper for the read-only agricultural database pool.

Injected into the LangGraph executor node via RunnableConfig.
Uses asyncpg for maximum performance on generated SELECT queries.
"""

import asyncpg
import asyncio
import time
from typing import List, Dict, Any
from talk2db.exceptions import DatabaseExecutionError
from talk2db.logger import get_logger
from talk2db.config import settings

logger = get_logger(__name__)

class DBExecutor:
    """
    Handles secure execution of validated SQL against PostgreSQL
    using a dependency-injected asyncpg connection pool.
    """

    def __init__(self, pool: asyncpg.Pool):
        """
        Initializes the executor with a dependency-injected asyncpg pool.

        Args:
            pool: An asyncpg connection pool connected to the read-only agricultural database.
        """
        self.pool = pool

    async def execute_query(self, query: str, timeout: float = settings.db_timeout_seconds) -> List[Dict[str, Any]]:
        """
        Executes a validated SELECT query against PostgreSQL.
        Enforces a strict statement timeout (default 3000ms).

        Args:
            query: The validated SQL query string.
            timeout: Maximum execution time in seconds.

        Returns:
            A list of dictionaries representing the result rows.

        Raises:
            DatabaseExecutionError: On any database or timeout failure.
        """
        logger.debug(f"Executing SQL query with {timeout}s timeout: {query}")
        start_time = time.monotonic()
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(query, timeout=timeout)
                elapsed = time.monotonic() - start_time
                logger.info(f"Query executed successfully in {elapsed:.3f}s, returned {len(records)} rows.")
                return [dict(record) for record in records]

        except asyncpg.exceptions.PostgresError as e:
            logger.error(f"Postgres execution error: {e}")
            raise DatabaseExecutionError(f"Database Execution Error: {str(e)}")
        except asyncio.TimeoutError:
            logger.error(f"Query timed out after {timeout} seconds.")
            raise DatabaseExecutionError(
                "Database Execution Error: Query execution exceeded the 3000ms timeout."
            )
        except Exception as e:
            logger.exception(f"Unexpected error during query execution: {e}")
            raise DatabaseExecutionError(f"Unexpected Execution Error: {str(e)}")
