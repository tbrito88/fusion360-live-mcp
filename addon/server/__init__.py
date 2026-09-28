"""Fusion360LiveMCP Server Package — v2 (CustomEvent bridge architecture)"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_PATH = os.path.join(os.path.expanduser("~"), "fusion360livemcp.log")

_logger = logging.getLogger("fusion360livemcp")
_logger.setLevel(logging.DEBUG)

# File handler — rotates at 2 MB, keeps 3 backups
_fh = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"))
_logger.addHandler(_fh)

# Also echo to Fusion's TEXT COMMANDS (stdout/stderr)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(logging.Formatter("[MCP] %(message)s"))
_logger.addHandler(_sh)


def get_logger(name: str = None) -> logging.Logger:
    """Return a child logger: ``get_logger("bridge")`` → ``fusion360livemcp.bridge``."""
    if name:
        return _logger.getChild(name)
    return _logger
