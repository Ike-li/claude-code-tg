"""Process and PID helpers for tgcc-managed background instances."""

import os
import signal
import time
from contextlib import suppress
from pathlib import Path

from claude_code_tg.file_security import open_rejecting_symlink_read


def send_signal_to_process_tree(pid: int, sig: signal.Signals) -> None:
    """Signal a process group when pid is its group leader, else the process."""
    if os.name != "nt" and hasattr(os, "getpgid"):
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
                return
        except ProcessLookupError:
            raise
        except OSError:
            pass
    os.kill(pid, sig)


def read_pid(pidfile: Path) -> int | None:
    if pidfile.is_symlink() or not pidfile.exists():
        return None
    try:
        with open_rejecting_symlink_read(pidfile) as f:
            pid = int(f.read().strip())
    except ValueError:
        with suppress(OSError):
            pidfile.unlink(missing_ok=True)
        return None
    except OSError:
        return None

    try:
        os.kill(pid, 0)
        return pid
    except ProcessLookupError:
        with suppress(OSError):
            pidfile.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid  # Process exists but we lack permission to probe it


def wait_for_exit(pid: int, timeout: float = 10) -> bool:
    """Wait for a process to exit. Returns True if exited, False on timeout."""
    for _ in range(int(timeout * 10)):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            return True
    return False
