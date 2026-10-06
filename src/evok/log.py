import logging
from collections import deque

logger = logging.getLogger('evok')


def read_log_tail(path, lines: int) -> str:
    """ Return the last lines of the log file """
    with open(path, encoding='utf-8', errors='replace') as f:
        return ''.join(deque(f, maxlen=lines))
