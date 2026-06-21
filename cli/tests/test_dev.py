"""Smoke tests for ``cli.commands.dev``."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.commands import dev
from cli.config import Config, load_config


def _cfg() -> Config:
    # Use the real env-file loader so test config mirrors production
    # behaviour (``.env.template`` -> ``.env`` -> ``os.environ``).
    # No hardcoded values: ``.env.template`` is the single source of
    # truth, same as ``cli.commands.start``/``dev`` at runtime.
    return load_config()


def test_has_vite_false_when_missing(tmp_path: Path):
    assert dev._has_vite(tmp_path) is False


def test_has_vite_true_when_in_root_node_modules(tmp_path: Path):
    (tmp_path / "node_modules" / "vite").mkdir(parents=True)
    assert dev._has_vite(tmp_path) is True


def test_has_vite_true_when_in_client_node_modules(tmp_path: Path):
    (tmp_path / "client" / "node_modules" / "vite").mkdir(parents=True)
    assert dev._has_vite(tmp_path) is True


def test_clear_vite_cache_no_op_when_missing(tmp_path: Path):
    # Just shouldn't raise.
    dev._clear_vite_cache(tmp_path)


def test_clear_vite_cache_removes_present(tmp_path: Path):
    cache = tmp_path / "client" / "node_modules" / ".vite"
    cache.mkdir(parents=True)
    (cache / "deps.json").write_text("{}")
    dev._clear_vite_cache(tmp_path)
    assert not cache.exists()


def test_build_specs_dev_uses_vite_when_available(tmp_path: Path):
    cfg = _cfg()
    specs = dev._build_specs(tmp_path, cfg, daemon=False, use_vite=True)
    by_name = {s.name: s for s in specs}
    assert by_name["client"].argv[:3] == ["pnpm", "run", "client:start"]


def test_build_specs_dev_falls_back_to_static_without_vite(tmp_path: Path):
    cfg = _cfg()
    specs = dev._build_specs(tmp_path, cfg, daemon=False, use_vite=False)
    by_name = {s.name: s for s in specs}
    assert by_name["client"].argv[0] == "node"
    assert "serve-client.js" in by_name["client"].argv[1]


def test_build_specs_daemon_binds_0_0_0_0_with_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MACHINA_ALLOW_UNSAFE_PUBLIC_BIND", "true")
    cfg = _cfg()
    specs = dev._build_specs(tmp_path, cfg, daemon=True, use_vite=True)
    server_argv = next(s for s in specs if s.name == "server").argv
    assert "0.0.0.0" in server_argv


def test_build_specs_daemon_rejects_public_bind_with_default_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("MACHINA_ALLOW_UNSAFE_PUBLIC_BIND", raising=False)
    monkeypatch.setenv("VITE_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "dev-secret-key-12345678901234567890123456789012")
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", "dev-encryption-key-12345678901234567890123456")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev-jwt-secret-key-12345678901234567890")
    cfg = _cfg()

    with pytest.raises(SystemExit):
        dev._build_specs(tmp_path, cfg, daemon=True, use_vite=True)


def test_build_specs_non_daemon_binds_127_0_0_1(tmp_path: Path):
    cfg = _cfg()
    specs = dev._build_specs(tmp_path, cfg, daemon=False, use_vite=True)
    server_argv = next(s for s in specs if s.name == "server").argv
    assert "127.0.0.1" in server_argv


def test_build_specs_dev_always_includes_temporal(tmp_path: Path):
    cfg = _cfg()
    specs = dev._build_specs(tmp_path, cfg, daemon=False, use_vite=True)
    assert any(s.name == "temporal" for s in specs)
