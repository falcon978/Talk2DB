"""
Provides a standardized logging configuration for the agent.
"""

import logging
import sys

def get_logger(name: str) -> logging.Logger:
    """
    Configures and returns a strictly formatted standard library logger.
    Ensures uniform log output across all modules.
    
    Args:
        name: The name of the module requesting the logger (typically __name__).
        
    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)
    
    # Prevent duplicate handlers if get_logger is called multiple times for the same module
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            fmt="[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Do not propagate up to the root logger to avoid duplicate log prints
        logger.propagate = False
        
    return logger
