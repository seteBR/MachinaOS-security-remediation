"""Cross-platform helpers for supervised binaries.

Stdlib + psutil only — no exotic abstractions. These are extracted from
the patterns already in production use across browser_service.py,
process_service.py, and the WhatsApp runtime, so behaviour is unchanged
when subclasses adopt the supervisor base.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Callable, Optional

import anyio
import psutil


def kill_tree(pid: int) -> None:
    """Kill a process and all descendants. Cross-platform via psutil.

    Defensively guards every psutil call against ``NoSuchProcess`` to
    survive races with fast-exiting children. Used by process_service,
    browser_service, and BaseProcessSupervisor for tree termination.
    """
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    try:
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in children:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        parent.kill()
    except psutil.NoSuchProcess:
        pass


async def terminate_then_kill(
    proc: anyio.abc.Process,
    *,
    grace: float = 5.0,
    use_ctrl_break: bool = False,
) -> None:
    """Send a graceful stop, wait ``grace`` seconds, then tree-kill.

    POSIX path: ``proc.terminate()`` (SIGTERM), wait, ``kill_tree()``.
    Windows graceful path (``use_ctrl_break=True``, requires the process
    to have been spawned with ``CREATE_NEW_PROCESS_GROUP``):
    ``os.kill(pid, CTRL_BREAK_EVENT)`` — the only way to send a real
    SIGINT-equivalent on Windows.
    """
    if proc.returncode is not None:
        return

    if use_ctrl_break and sys.platform == "win32":
        try:
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        except (ProcessLookupError, OSError):
            pass
    else:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass

    with anyio.move_on_after(grace):
        await proc.wait()

    if proc.returncode is None:
        kill_tree(proc.pid)
        await proc.wait()


async def drain_stream(
    stream: Optional[anyio.abc.ByteReceiveStream],
    log_fn: Callable[[str], None],
    *,
    prefix: str = "",
) -> None:
    """Forward subprocess output line-by-line to a logger callable.

    Safe against cancellation and closed streams. ``log_fn`` is something
    like ``logger.info`` or ``logger.error``. Lines are decoded as UTF-8
    with ``errors="replace"`` so binary garbage never crashes the drain.
    """
    if stream is None:
        return
    buf = b""
    try:
        async for chunk in stream:
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    log_fn(f"{prefix}{text}" if prefix else text)
        if buf:
            text = buf.decode("utf-8", errors="replace").rstrip()
            if text:
                log_fn(f"{prefix}{text}" if prefix else text)
    except (anyio.ClosedResourceError, anyio.EndOfStream, asyncio.CancelledError):
        pass
    except Exception as exc:  # pragma: no cover — defensive
        logging.getLogger(__name__).debug("drain_stream ended: %s", exc)
