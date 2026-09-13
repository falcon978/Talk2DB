"""
Provides AST-level SQL validation and guardrails using sqlglot.
"""

import sqlglot
from sqlglot import exp
from agri_sql_agent.exceptions import SQLSecurityViolation
from agri_sql_agent.logger import get_logger
from agri_sql_agent.config import settings

logger = get_logger(__name__)

def validate_and_format_sql(sql_query: str) -> str:
    """
    Parses the generated SQL using sqlglot.
    Enforces that the statement is exclusively a SELECT.
    Blocks DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE, EXECUTE.
    Injects a LIMIT 100 clause if no LIMIT is present.
    """
    try:
        # Parse the query dialect as postgres
        parsed = sqlglot.parse(sql_query, read="postgres")
        if not parsed:
            logger.warning("AST Validation failed: Empty or invalid SQL generated.")
            raise SQLSecurityViolation("Empty or invalid SQL generated.")
            
        # Ensure there is exactly one statement (prevent multi-statement injections)
        if len(parsed) > 1:
            logger.warning("AST Validation failed: Multiple SQL statements detected.")
            raise SQLSecurityViolation("Multiple SQL statements detected. Only a single SELECT is allowed.")
            
        statement = parsed[0]
        
        # Guardrail: Must be a SELECT, UNION, or INTERSECT statement
        if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect)):
            logger.warning(f"AST Validation failed: Destructive or non-SELECT query detected: {type(statement).__name__}")
            raise SQLSecurityViolation(f"Destructive or non-SELECT query detected: {type(statement).__name__}")
            
        # Additional deep check for destructive nodes in subqueries/CTEs
        _BLOCKED_COMMANDS = {"TRUNCATE", "EXECUTE"}
        for node in statement.walk():
            expr = node[0]
            # node[0] gives the actual expression instance in the generator
            if isinstance(expr, (exp.Delete, exp.Update, exp.Insert, exp.Drop, exp.Create, exp.Alter)):
                logger.warning("AST Validation failed: Destructive sub-statement detected inside query.")
                raise SQLSecurityViolation("Destructive sub-statement detected inside query.")
            # sqlglot parses TRUNCATE and EXECUTE as exp.Command — check the command keyword explicitly
            if isinstance(expr, exp.Command) and expr.this.upper() in _BLOCKED_COMMANDS:
                logger.warning(f"AST Validation failed: Blocked command detected: {expr.this}")
                raise SQLSecurityViolation(f"Blocked command detected: {expr.this}")
                
            # Guardrail: Prevent massive over-fetching via short wildcards (e.g. ILIKE '%n%')
            if isinstance(expr, (exp.Like, exp.ILike)):
                if isinstance(expr.right, exp.Literal):
                    val = expr.right.this
                    if val.startswith("%") and val.endswith("%"):
                        inner_str = val[1:-1]
                        if len(inner_str) < settings.wildcard_min_length:
                            logger.warning(f"AST Validation failed: Over-fetching wildcard detected ('%{inner_str}%').")
                            raise SQLSecurityViolation(f"Wildcard search '%{inner_str}%' is too broad. Use at least {settings.wildcard_min_length} characters or an exact match.")
                
        # Guardrail: Inject LIMIT if missing
        if not statement.args.get("limit"):
            logger.debug(f"AST Validation: Injecting LIMIT {settings.result_row_limit} clause.")
            statement = statement.limit(settings.result_row_limit)
            
        formatted_sql = statement.sql(dialect="postgres")
        logger.debug("AST Validation successful.")
        return formatted_sql
        
    except sqlglot.errors.ParseError as e:
        logger.error(f"SQL Syntax Error during AST parsing: {e}")
        raise SQLSecurityViolation(f"SQL Syntax Error: {str(e)}")
