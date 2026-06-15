"""Worker self-restart in TemporalWorkerManager._run_worker.

The Temporal worker shuts down on a transient poll failure rather than
auto-retrying, and the run task is detached (main.py's startup retry loop
has already returned). ``_run_worker`` now re-runs the same worker instance
with doubling backoff on a crash, while cancellation (from ``stop()``)
always wins so shutdown is never delayed by a restart. Backoff knobs come
from Settings (env-driven); the conftest stubs Settings, so we patch it to
a SimpleNamespace with tiny real backoffs.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.temporal.worker import TemporalWorkerManager


def _patch_backoff():
    return patch(
        "core.config.Settings",
        side_effect=lambda: SimpleNamespace(
            temporal_worker_restart_backoff_seconds=0.001,
            temporal_worker_restart_backoff_max_seconds=0.002,
        ),
    )


def _manager_with_run(fake_run) -> TemporalWorkerManager:
    mgr = TemporalWorkerManager(client=MagicMock(), task_queue="q")
    worker = MagicMock()
    worker.run = fake_run
    mgr._worker = worker
    return mgr


async def test_worker_restarts_after_transient_crash():
    calls = {"n": 0}

    async def fake_run():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient poll failure")
        await asyncio.Event().wait()  # healthy run blocks

    mgr = _manager_with_run(fake_run)

    with _patch_backoff():
        task = asyncio.create_task(mgr._run_worker())
        await asyncio.sleep(0.05)  # allow crash + restart
        assert calls["n"] == 2  # restarted exactly once
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_cancellation_does_not_restart():
    calls = {"n": 0}

    async def fake_run():
        calls["n"] += 1
        await asyncio.Event().wait()  # healthy run blocks until cancelled

    mgr = _manager_with_run(fake_run)

    with _patch_backoff():
        task = asyncio.create_task(mgr._run_worker())
        await asyncio.sleep(0.02)
        assert calls["n"] == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls["n"] == 1  # cancellation wins; not restarted
