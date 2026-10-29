"""Process hardening: keep the backend's memory and environ unreadable by agents."""

import ctypes
import ctypes.util
import logging
import sys

logger = logging.getLogger(__name__)

PR_SET_DUMPABLE = 4


def make_non_dumpable() -> bool:
    """Mark this process non-dumpable so same-uid processes cannot read /proc/<pid>/environ.

    Linux only; returns False (without raising) elsewhere or on failure.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0:
            return True
        logger.warning("prctl(PR_SET_DUMPABLE) failed (errno %d): the process stays dumpable", ctypes.get_errno())
    except (OSError, AttributeError) as exc:
        logger.warning("Could not call prctl(PR_SET_DUMPABLE): %s; the process stays dumpable", exc)
    return False
