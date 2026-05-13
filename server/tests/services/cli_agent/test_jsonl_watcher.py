"""Unit tests for :mod:`services.cli_agent.jsonl_watcher`.

Covers :class:`JsonlWatcher` (tail-f one file) and
:class:`JsonlDirWatcher` (detect new files). Both run with real
tempfiles; no PTY / claude / network dependencies.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from services.cli_agent.jsonl_watcher import (
    JsonlDirWatcher,
    JsonlWatcher,
    session_uuid_from_jsonl_path,
)


class TestJsonlWatcher:
    @pytest.fixture
    def tmp_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            yield path

    async def test_tails_newly_written_lines(self, tmp_jsonl):
        events: List[Dict[str, Any]] = []

        async def on_event(event):
            events.append(event)

        watcher = JsonlWatcher(tmp_jsonl, on_event=on_event, poll_interval=0.05)
        await watcher.start()
        try:
            # Wait briefly so the loop has a chance to open the file.
            await asyncio.sleep(0.1)
            with tmp_jsonl.open("ab") as fh:
                fh.write(json.dumps({"type": "system", "subtype": "init"}).encode() + b"\n")
                fh.write(json.dumps({"type": "assistant", "message": {"content": "hi"}}).encode() + b"\n")
            # Give the poll loop a couple ticks.
            await asyncio.sleep(0.2)
        finally:
            await watcher.stop()

        assert len(events) == 2
        assert events[0]["type"] == "system"
        assert events[1]["type"] == "assistant"

    async def test_ignores_garbage_lines(self, tmp_jsonl):
        events: List[Dict[str, Any]] = []

        async def on_event(event):
            events.append(event)

        watcher = JsonlWatcher(tmp_jsonl, on_event=on_event, poll_interval=0.05)
        await watcher.start()
        try:
            await asyncio.sleep(0.1)
            with tmp_jsonl.open("ab") as fh:
                fh.write(b"not valid json\n")
                fh.write(json.dumps({"type": "result"}).encode() + b"\n")
                fh.write(b"\n")  # blank
                fh.write(b"   \n")  # whitespace
            await asyncio.sleep(0.2)
        finally:
            await watcher.stop()

        # Only the valid line dispatched.
        assert len(events) == 1
        assert events[0]["type"] == "result"

    async def test_stop_is_idempotent(self, tmp_jsonl):
        async def on_event(event):  # pragma: no cover — never fires
            pass

        watcher = JsonlWatcher(tmp_jsonl, on_event=on_event, poll_interval=0.05)
        await watcher.start()
        await watcher.stop()
        await watcher.stop()  # second stop must not raise

    async def test_handler_exception_doesnt_break_loop(self, tmp_jsonl):
        events: List[Dict[str, Any]] = []

        async def on_event(event):
            if event.get("type") == "boom":
                raise RuntimeError("handler exploded")
            events.append(event)

        watcher = JsonlWatcher(tmp_jsonl, on_event=on_event, poll_interval=0.05)
        await watcher.start()
        try:
            await asyncio.sleep(0.1)
            with tmp_jsonl.open("ab") as fh:
                fh.write(json.dumps({"type": "boom"}).encode() + b"\n")
                fh.write(json.dumps({"type": "good"}).encode() + b"\n")
            await asyncio.sleep(0.2)
        finally:
            await watcher.stop()

        assert any(e["type"] == "good" for e in events)


class TestJsonlDirWatcher:
    @pytest.fixture
    def tmp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    async def test_detects_newly_created_jsonl(self, tmp_dir):
        new_files: List[Path] = []

        async def on_new(path):
            new_files.append(path)

        watcher = JsonlDirWatcher(tmp_dir, on_new_file=on_new, poll_interval=0.05)
        await watcher.start()
        try:
            await asyncio.sleep(0.1)
            (tmp_dir / "abc-123.jsonl").write_text("")
            (tmp_dir / "def-456.jsonl").write_text("")
            await asyncio.sleep(0.2)
        finally:
            await watcher.stop()

        names = {p.name for p in new_files}
        assert "abc-123.jsonl" in names
        assert "def-456.jsonl" in names

    async def test_baseline_files_not_fired(self, tmp_dir):
        # File present BEFORE start = baseline; should NOT fire callback.
        (tmp_dir / "existing.jsonl").write_text("")

        new_files: List[Path] = []

        async def on_new(path):
            new_files.append(path)

        watcher = JsonlDirWatcher(tmp_dir, on_new_file=on_new, poll_interval=0.05)
        await watcher.start()
        try:
            await asyncio.sleep(0.15)
            # Add a new file post-start.
            (tmp_dir / "fresh.jsonl").write_text("")
            await asyncio.sleep(0.2)
        finally:
            await watcher.stop()

        names = [p.name for p in new_files]
        assert "existing.jsonl" not in names
        assert "fresh.jsonl" in names

    async def test_non_jsonl_files_ignored(self, tmp_dir):
        new_files: List[Path] = []

        async def on_new(path):
            new_files.append(path)

        watcher = JsonlDirWatcher(tmp_dir, on_new_file=on_new, poll_interval=0.05)
        await watcher.start()
        try:
            await asyncio.sleep(0.1)
            (tmp_dir / "session.jsonl").write_text("")
            (tmp_dir / "session.txt").write_text("")
            (tmp_dir / "session.json").write_text("")
            await asyncio.sleep(0.2)
        finally:
            await watcher.stop()

        names = {p.name for p in new_files}
        assert names == {"session.jsonl"}


class TestSessionUuidFromJsonlPath:
    def test_extracts_uuid_stem(self):
        path = Path("/some/dir/abc-123-def-456.jsonl")
        assert session_uuid_from_jsonl_path(path) == "abc-123-def-456"

    def test_returns_none_for_non_jsonl(self):
        assert session_uuid_from_jsonl_path(Path("foo.txt")) is None
        assert session_uuid_from_jsonl_path(Path("foo.json")) is None

    def test_returns_none_for_empty_stem(self):
        # A path like `.jsonl` (no stem) returns None.
        assert session_uuid_from_jsonl_path(Path(".jsonl")) is None
