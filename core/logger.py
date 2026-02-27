import logging
import sys

def get_app_logger(name: str) -> logging.Logger:
    """
    Creates and configures a standard logger for the application.
    Outputs to standard output (console) with a consistent format.
    """
    logger = logging.getLogger(name)
    
    # Only configure handlers if they don't already exist to avoid duplicates
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # Create formatted layout
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(console_handler)
        
        # Prevent propagation to the root logger to avoid double logging
        logger.propagate = False
        
    return logger
