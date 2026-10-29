"""Process hardening: keep the backend's memory and environ unreadable by agents."""

import ctypes
import ctypes.util
import sys

PR_SET_DUMPABLE = 4


def make_non_dumpable() -> bool:
    """Mark this process non-dumpable so same-uid processes cannot read /proc/<pid>/environ.

    Linux only; returns False (without raising) elsewhere or on failure.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        return libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False
