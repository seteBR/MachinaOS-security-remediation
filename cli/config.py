"""Project configuration -- typed view over ``.env`` / ``.env.template``.

Stdlib-only env-var loader. ``.env.template`` ships with every install
and is the canonical source of defaults; ``.env`` (created by
``scripts/postinstall.js`` on ``npm install -g machinaos``) layers user
overrides on top; ``os.environ`` wins over both at the call site (so
``TEMPORAL_BACKEND=foo machina start`` still works).

Merged values are pushed into ``os.environ`` so downstream consumers
that read ``os.environ`` directly (e.g.
:mod:`cli.commands._temporal_specs` deciding which Temporal ServiceSpec
set to build) see the same view as this module. Without that push the
supervisor's environment lookups would return ``None`` even after
``postinstall.js`` copied ``.env.template`` to ``.env`` -- the bug that
made v0.0.79's ``npm install -g machinaos && machina start`` path
silently fall back to the sqlite Temporal spec instead of the
``postgres`` default declared in ``.env.template``.

No Python-side hardcoded defaults: ``.env.template`` is the single
source of truth. If the template is missing (broken install), we error
out loudly with a remediation hint rather than silently substituting
duplicate hardcoded values that drift from the shipped template.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cli.platform_ import project_root


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key.strip()] = value
    return out


def _require(env: dict[str, str], key: str) -> str:
    raw = env.get(key)
    if raw is None:
        raise KeyError(
            f"{key} missing from .env / .env.template -- "
            "reinstall (``npm install -g machinaos``) or restore the template."
        )
    return raw


def _int(env: dict[str, str], key: str) -> int:
    return int(_require(env, key))


def _bool(env: dict[str, str], key: str) -> bool:
    return _require(env, key).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    """Typed view over the merged ``.env.template`` + ``.env`` + process
    env. No field defaults -- every value originates in the env files so
    the published shape matches what users see (and can edit) in their
    ``.env``."""

    client_port: int
    backend_port: int
    whatsapp_port: int
    nodejs_port: int
    temporal_address: str
    temporal_enabled: bool
    temporal_backend: str

    @property
    def temporal_port(self) -> int:
        try:
            return int(self.temporal_address.rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            return 7233

    @property
    def all_ports(self) -> list[int]:
        return [
            self.client_port,
            self.backend_port,
            self.whatsapp_port,
            self.nodejs_port,
            self.temporal_port,
        ]


@lru_cache(maxsize=1)
def load_config(root: Path | None = None) -> Config:
    """Load + merge ``.env.template`` (baseline) and ``.env`` (overrides).

    Precedence (low -> high): ``.env.template`` < ``.env`` < ``os.environ``.

    Merged file values are pushed into ``os.environ`` so any downstream
    ``os.environ.get(...)`` lookup sees the same view -- without
    overwriting existing process env vars (matches python-dotenv's
    default ``override=False`` semantics).
    """
    root = root or project_root()
    template = root / ".env.template"
    user = root / ".env"

    if not template.exists():
        raise FileNotFoundError(
            f".env.template not found at {template}. "
            "Reinstall (``npm install -g machinaos``) or restore the template "
            "from the source tree."
        )

    # Layer: .env.template (canonical defaults) <- .env (user override)
    merged: dict[str, str] = _load_env_file(template)
    merged.update(_load_env_file(user))

    # Push file values into the process environment so downstream
    # ``os.environ.get(...)`` reads see them. Process env still wins --
    # only keys missing from the process environment are inserted.
    for key, value in merged.items():
        os.environ.setdefault(key, value)

    # Final view layers process env on top of file env.
    env = {**merged, **os.environ}

    return Config(
        client_port=_int(env, "VITE_CLIENT_PORT"),
        backend_port=_int(env, "PYTHON_BACKEND_PORT"),
        whatsapp_port=_int(env, "WHATSAPP_RPC_PORT"),
        nodejs_port=_int(env, "NODEJS_EXECUTOR_PORT"),
        temporal_address=_require(env, "TEMPORAL_SERVER_ADDRESS"),
        temporal_enabled=_bool(env, "TEMPORAL_ENABLED"),
        temporal_backend=_require(env, "TEMPORAL_BACKEND"),
    )
