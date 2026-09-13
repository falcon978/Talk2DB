"""
Provides custom callbacks for LangChain/LangGraph execution.
"""

from langchain_core.callbacks import BaseCallbackHandler


class TokenCounterCallback(BaseCallbackHandler):
    """
    Tracks cumulative token usage across LLM invocations within a single graph execution.
    Extracts token counts from Ollama's usage metadata or LangChain's AIMessage usage fields.
    """

    def __init__(self):
        self.total_tokens = 0
        
    def on_llm_end(self, response, **kwargs):
        """
        Accumulates token counts from the LLM response.
        Handles both Ollama's native token_usage format and LangChain's AIMessage usage_metadata.
        """
        # Extract Ollama's specific usage metadata if available
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            self.total_tokens += usage.get("total_tokens", 0)
        # Langchain AIMessage usage_metadata extraction for newer versions
        elif response.generations and len(response.generations) > 0:
            msg = response.generations[0][0].message
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                self.total_tokens += msg.usage_metadata.get("input_tokens", 0) + msg.usage_metadata.get("output_tokens", 0)
