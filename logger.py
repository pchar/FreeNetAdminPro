"""
FreeNetAdminPro structured logger -- 3 verbosity levels with thread identification.

Levels (increasing verbosity):
    INFO   -- high-level logical descriptions (what phase is running)
    DEBUG  -- deep traces with input/output parameters
    TRACE  -- every instruction line-by-line with source code location

Thread identification:
    Each logger instance carries a "nick" (e.g. "GUI", "Worker/scan").
    Threads can be named via set_thread_nick().
    Logs look like:  [TRACE] [Worker/scan] col 0: insertRow(0) -- main.py:682

Usage:
    from logger import get_logger, set_thread_nick

    set_thread_nick("Worker/scan")       # name the current thread
    log = get_logger("main.MCPWorker")   # per-instance logger
    log.info("Starting scan")
    log.debug("Got %d devices", 42)
    log.trace("Emitting device_signal row=%d", row)
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any


# -- Level constants ----------------------------------------------------------
TRACE = 5  # below DEBUG
logging.addLevelName(TRACE, "TRACE")

_LEVEL_NAMES: dict[int, str] = {
    logging.INFO: "INFO",
    logging.DEBUG: "DEBUG",
    TRACE: "TRACE",
}

# -- Thread nickname registry -------------------------------------------------
_thread_nicks: dict[int, str] = {}


def set_thread_nick(nick: str) -> None:
    """Associate a human-readable nickname with the current thread."""
    tid = threading.current_thread().ident
    assert tid is not None
    _thread_nicks[tid] = nick


def _get_nick(thread_id: int | None = None) -> str:
    """Return nick for *thread_id*, falling back to numeric ID."""
    if thread_id is None:
        thread_id = threading.current_thread().ident
    assert thread_id is not None
    return _thread_nicks.get(thread_id, str(thread_id))


# -- Custom formatter ---------------------------------------------------------
class _FreeNetFormatter(logging.Formatter):
    """FORMAT: [LEVEL] [thread_nick] message -- module:lineno

    Critical: do NOT override record.msg then call super().format() —
    that re-invokes getMessage() with stale args and crashes on % chars.
    Instead, build the full string manually.
    """

    def __init__(self, datefmt: str = "%H:%M:%S"):
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        nick = _get_nick(getattr(record, "thread_id", None))
        module = getattr(record, "module", "")
        lineno = getattr(record, "lineno", 0)
        src = f"{module}:{lineno}" if module else f"???:{lineno}"
        level = _LEVEL_NAMES.get(record.levelno, record.levelname)
        # getMessage() does msg % args once; use the result, then build the
        # final string ourselves so super().format() is never called with
        # a modified record.msg containing % characters.
        msg = f"[{nick}] {record.getMessage()}"
        datestr = self.formatTime(record, self.datefmt)
        return f"{datestr} [{level}] {msg} -- {src}"


# -- Custom logger class with trace() -----------------------------------------
class _FreeNetLogger(logging.Logger):
    """Logger subclass with a .trace() method."""

    def trace(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(TRACE, msg, *args, **kwargs)


# -- Factory ------------------------------------------------------------------
_logger_registry: dict[str, logging.Logger] = {}


def get_logger(
    name: str,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """Return a configured logger.

    *name*     -- unique identifier for the logger instance
    *level*    -- minimum level to emit (INFO / DEBUG / TRACE)
    """
    if name in _logger_registry:
        return _logger_registry[name]

    # Create as the custom subclass so .trace() is natively known
    log = _FreeNetLogger(name)
    log.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(_FreeNetFormatter())
    log.addHandler(handler)

    _logger_registry[name] = log
    return log
