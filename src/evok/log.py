import logging
from collections import deque

# the parent of the loggers of the modules (logging.getLogger(__name__)), its level and handlers apply to all of them
package_logger = logging.getLogger("evok")


def read_log_tail(path, lines: int) -> str:
    """Return the last lines of the log file"""
    with open(path, encoding="utf-8", errors="replace") as f:
        return "".join(deque(f, maxlen=lines))
