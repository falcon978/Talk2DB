"""
Defines custom exceptions for the agent's failure modes.
"""

class SQLSecurityViolation(Exception):
    """Raised when a generated SQL query violates security guardrails."""
    pass

class DatabaseExecutionError(Exception):
    """Raised when query execution fails or times out."""
    pass

class LLMGenerationError(Exception):
    """Raised when structured LLM output generation or parsing fails."""
    pass

class StateValidationError(Exception):
    """Raised when the graph state is invalid or missing required context."""
    pass

class ResourceInitializationError(Exception):
    """Raised when critical backend resources (pools, graph) fail to initialize."""
    pass
