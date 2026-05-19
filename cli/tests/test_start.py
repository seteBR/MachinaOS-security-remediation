"""Smoke tests for ``cli.commands.start``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cli import buildenv
from cli.commands import start
from cli.config import Config, load_config


def _cfg() -> Config:
    # Use the real env-file loader so test config mirrors production
    # behaviour (``.env.template`` -> ``.env`` -> ``os.environ``).
    # No hardcoded values: ``.env.template`` is the single source of
    # truth, same as ``cli.commands.start`` at runtime.
    return load_config()


def test_venv_python_returns_none_when_missing(tmp_path: Path):
    assert buildenv.venv_python(tmp_path) is None


def test_venv_python_finds_windows_layout(tmp_path: Path):
    win_py = tmp_path / "server" / ".venv" / "Scripts" / "python.exe"
    win_py.parent.mkdir(parents=True)
    win_py.write_text("")
    assert buildenv.venv_python(tmp_path) == win_py


def test_venv_python_finds_posix_layout(tmp_path: Path):
    posix_py = tmp_path / "server" / ".venv" / "bin" / "python"
    posix_py.parent.mkdir(parents=True)
    posix_py.write_text("")
    assert buildenv.venv_python(tmp_path) == posix_py


def test_temporal_running_false_when_port_closed():
    # TCP-probe based check: returns False when nothing is listening on
    # the configured gRPC port. Mock the probe directly instead of the
    # legacy subprocess-spawn implementation.
    cfg = _cfg()
    with patch("cli.tcp.probe_tcp_port_sync", return_value=False):
        assert start._temporal_running(cfg) is False


def test_build_specs_skips_temporal_when_already_running(tmp_path: Path):
    cfg = _cfg()
    specs = start._build_specs(tmp_path, cfg, temporal_running=True)
    assert {s.name for s in specs} == {"client", "server"}


def test_build_specs_includes_temporal_when_not_running(tmp_path: Path):
    cfg = _cfg()
    specs = start._build_specs(tmp_path, cfg, temporal_running=False)
    names = {s.name for s in specs}
    # Backend-agnostic: sqlite yields {"client", "server", "temporal"};
    # postgres yields {"client", "server", "postgres", "temporal"}.
    assert {"client", "server", "temporal"} <= names


def test_build_specs_assigns_ready_ports(tmp_path: Path):
    cfg = _cfg()
    specs = start._build_specs(tmp_path, cfg, temporal_running=False)
    by_name = {s.name: s for s in specs}
    assert by_name["client"].ready_port == cfg.client_port
    assert by_name["server"].ready_port == cfg.backend_port
    assert by_name["temporal"].ready_port == cfg.temporal_port
