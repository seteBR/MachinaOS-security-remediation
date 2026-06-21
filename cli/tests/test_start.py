"""Smoke tests for ``cli.commands.start``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cli.commands import start
from cli.config import Config, load_config


def _cfg() -> Config:
    # Use the real env-file loader so test config mirrors production
    # behaviour (``.env.template`` -> ``.env`` -> ``os.environ``).
    # No hardcoded values: ``.env.template`` is the single source of
    # truth, same as ``cli.commands.start`` at runtime.
    return load_config()


# The previous ``test_venv_python_*`` cases verified a custom helper
# that walked ``server/.venv/{Scripts,bin}`` paths. That helper has been
# retired: subprocess launchers now build their argv via
# :func:`cli.run.uv_run`, which delegates interpreter selection to
# ``uv run`` (https://docs.astral.sh/uv/reference/cli/#uv-run). Nothing
# platform-specific to assert from the CLI side anymore.


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


def test_build_specs_defaults_backend_to_localhost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MACHINA_BIND_HOST", raising=False)
    cfg = _cfg()
    specs = start._build_specs(tmp_path, cfg, temporal_running=True)
    server = {s.name: s for s in specs}["server"]
    assert "127.0.0.1" in server.argv


def test_build_specs_rejects_public_bind_when_auth_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MACHINA_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("VITE_AUTH_ENABLED", "false")
    monkeypatch.delenv("MACHINA_ALLOW_UNSAFE_PUBLIC_BIND", raising=False)
    cfg = _cfg()

    with pytest.raises(SystemExit):
        start._build_specs(tmp_path, cfg, temporal_running=True)


def test_build_specs_allows_explicit_unsafe_public_bind_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MACHINA_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("VITE_AUTH_ENABLED", "false")
    monkeypatch.setenv("MACHINA_ALLOW_UNSAFE_PUBLIC_BIND", "true")
    cfg = _cfg()

    specs = start._build_specs(tmp_path, cfg, temporal_running=True)
    server = {s.name: s for s in specs}["server"]
    assert "0.0.0.0" in server.argv


def test_build_specs_rejects_public_bind_with_default_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MACHINA_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("VITE_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "dev-secret-key-12345678901234567890123456789012")
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", "dev-encryption-key-12345678901234567890123456")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev-jwt-secret-key-12345678901234567890")
    monkeypatch.delenv("MACHINA_ALLOW_UNSAFE_PUBLIC_BIND", raising=False)
    cfg = _cfg()

    with pytest.raises(SystemExit):
        start._build_specs(tmp_path, cfg, temporal_running=True)
