#!/usr/bin/env python3
# procs.py — the subprocess registry: no dangling processes on quit.
#
# The workbench and the CLI spawn LLM/auth subprocesses (pi via the
# sensing path, the node OAuth driver via the workbench auth). If the
# app quits mid-call, those subprocesses must not be left behind — so
# every spawn registers here (with start_new_session=True, so the whole
# process group can be terminated), and kill_all() runs on exit.
#
# POSIX only (process groups) — the engine runs on macOS/Linux, and in
# the gondolin VM (Linux).

import os
import signal
import threading

_lock = threading.Lock()
_procs = set()


def register(proc):
    with _lock:
        _procs.add(proc)


def unregister(proc):
    with _lock:
        _procs.discard(proc)


def kill_all():
    """Terminate every live registered subprocess (by process group)."""
    with _lock:
        live = [p for p in _procs if p.poll() is None]
    for p in live:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                p.terminate()
            except OSError:
                pass
    for p in live:
        try:
            p.wait(timeout=3)
        except Exception:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    p.kill()
                except OSError:
                    pass
