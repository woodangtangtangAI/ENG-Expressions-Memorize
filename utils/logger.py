"""
Logging utility for the English Expression Database.

Provides a configured logger that outputs to both console (with emoji prefixes
and color formatting) and optionally to a log file.
"""

import logging
import sys


class EmojiColorFormatter(logging.Formatter):
    """Custom formatter that adds emoji prefixes and ANSI color codes."""

    # ANSI color codes
    COLORS = {
        logging.DEBUG:    "\033[36m",    # Cyan
        logging.INFO:     "\033[32m",    # Green
        logging.WARNING:  "\033[33m",    # Yellow
        logging.ERROR:    "\033[31m",    # Red
        logging.CRITICAL: "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"

    # Emoji prefixes
    EMOJIS = {
        logging.DEBUG:    "🔍",
        logging.INFO:     "✅",
        logging.WARNING:  "⚠️",
        logging.ERROR:    "❌",
        logging.CRITICAL: "🚨",
    }

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        emoji = self.EMOJIS.get(record.levelno, "")
        reset = self.RESET

        # Prepend emoji and wrap with color
        original_msg = record.msg
        record.msg = f"{emoji} {color}{original_msg}{reset}"
        formatted = super().format(record)
        record.msg = original_msg  # Restore original for other handlers
        return formatted


def setup_logger(name, log_file=None):
    """Set up and return a configured logger.

    The logger outputs to the console with emoji prefixes and ANSI color
    formatting. If a log_file path is provided, plain-text logs are also
    written to that file.

    Args:
        name (str): Name of the logger (typically the module name).
        log_file (str, optional): Path to a log file. If None, only console
            output is used.

    Returns:
        logging.Logger: A configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler with emoji + color
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(EmojiColorFormatter(fmt=log_format, datefmt=date_format))
    logger.addHandler(console_handler)

    # File handler (plain text, no color/emoji)
    if log_file:
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True) if os.path.dirname(log_file) else None
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))
        logger.addHandler(file_handler)

    return logger
