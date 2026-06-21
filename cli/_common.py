"""Cross-verb helpers shared by ``machina`` commands.

Centralises the four patterns that previously appeared inlined in
``start.py`` / ``dev.py`` / ``stop.py`` / ``clean.py`` / ``build.py``:

  - :func:`preflight`        -- ``load_config()`` + ``project_root()``
                                preamble every verb opens with.
  - :func:`free_all_ports`   -- ``for port in cfg.all_ports: kill_port``
                                loop; lazy-imports ``cli.ports`` so a
                                broken ``psutil`` install doesn't take
                                down the recovery verb.
  - :func:`build_backend_spec` -- the shared ``uv_run("uvicorn", ...)``
                                  ServiceSpec used by both ``start``
                                  and ``dev``.
  - :func:`error_block`      -- multi-line ``[red]Error: ...[/]``
                                formatter; lazy-imports ``cli.colors``.

No third-party packages are imported at module load time. Importing
this module from ``cli/commands/clean.py`` is safe even when
``rich`` / ``psutil`` / ``platformdirs`` are missing -- only the
helper that actually needs the dep pulls it in.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from cli.config import Config, load_config
from cli.platform_ import project_root, server_dir

if TYPE_CHECKING:
    from cli.ports import KillResult
    from cli.supervisor import ServiceSpec

# ``cli.run`` (and ``cli.supervisor`` via ``cli.colors``) transitively
# pull in ``rich``. They're only needed by ``build_backend_spec`` /
# ``error_block`` which themselves lazy-import. Keeping them out of the
# top-level import list means ``machina clean`` (which calls only
# ``preflight`` and ``free_all_ports``) loads even when ``rich`` /
# ``psutil`` / ``platformdirs`` are unavailable.

_PUBLIC_HOSTS = {"", "0.0.0.0", "::", "*"}
_UNSAFE_PUBLIC_BIND_OVERRIDE = "MACHINA_ALLOW_UNSAFE_PUBLIC_BIND"
_WEAK_SECRET_PREFIXES = {
    "SECRET_KEY": "dev-secret-key",
    "API_KEY_ENCRYPTION_KEY": "dev-encryption-key",
    "JWT_SECRET_KEY": "dev-jwt-secret-key",
}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def bind_host_from_env(default: str = "127.0.0.1") -> str:
    """Return the backend bind host, defaulting to localhost."""
    return os.environ.get("MACHINA_BIND_HOST") or default


def is_public_bind_host(host: str) -> bool:
    return host.strip().lower() in _PUBLIC_HOSTS


def validate_bind_security(host: str, *, surface: str = "backend") -> None:
    """Reject public binding when auth is disabled unless explicitly allowed."""
    if not is_public_bind_host(host):
        return

    if _truthy(os.environ.get(_UNSAFE_PUBLIC_BIND_OVERRIDE)):
        return

    auth_disabled = (os.environ.get("VITE_AUTH_ENABLED") or "").strip().lower() == "false"
    weak_secrets = [
        name
        for name, prefix in _WEAK_SECRET_PREFIXES.items()
        if (os.environ.get(name) or "").startswith(prefix)
    ]
    if auth_disabled or weak_secrets:
        reasons = []
        if auth_disabled:
            reasons.append("authentication is disabled")
        if weak_secrets:
            reasons.append(f"weak default secrets are configured: {', '.join(weak_secrets)}")
        error_block(
            f"Refusing to bind {surface} to {host!r}: {'; '.join(reasons)}.",
            [
                "Set VITE_AUTH_ENABLED=true, rotate default secrets, bind to 127.0.0.1, or use a trusted reverse proxy.",
                f"For local-only unsafe development, set {_UNSAFE_PUBLIC_BIND_OVERRIDE}=true explicitly.",
            ],
        )
        raise SystemExit(1)


def preflight(cfg: Config | None = None) -> tuple[Config, Path]:
    """Standard verb preamble: ``(load_config(), project_root())``.

    Pass an explicit ``cfg`` to avoid the lookup (e.g. when the caller
    already has one). ``load_config`` is ``@lru_cache``d, so repeated
    calls inside the same process are free regardless.
    """
    return cfg or load_config(), project_root()


def free_all_ports(cfg: Config) -> list[KillResult]:
    """Kill anything listening on ``cfg.all_ports``; return per-port
    results.

    Returns a list (not a count) so callers can render per-port status
    -- ``machina stop`` shows ``[OK]`` / ``[!!]`` markers and the killed
    PIDs, ``machina start`` and ``clean`` just want them gone. The
    helper centralises the iteration, callers pick the rendering.

    ``cli.ports`` is imported lazily so this module loads even when
    ``psutil`` (a transitive dep) is missing -- important for the
    recovery verb ``machina clean``.
    """
    from cli.ports import kill_port

    return [kill_port(port) for port in cfg.all_ports]


def build_backend_spec(
    cfg: Config,
    *,
    host: str,
    root: Path | None = None,
) -> "ServiceSpec":
    """The Python backend ``ServiceSpec`` shared by ``start`` and ``dev``.

    Routes through :func:`cli.run.uv_run` so the standardised
    ``uv run --no-sync`` flags stay in one place. ``host`` is the only
    differentiator.

    ``cli.run`` and ``cli.supervisor`` are lazy-imported so this module
    stays importable when their transitive ``rich`` dep is missing --
    ``machina clean`` doesn't call this and shouldn't pay for it.
    """
    from cli.run import uv_run
    from cli.supervisor import ServiceSpec

    return ServiceSpec(
        name="server",
        argv=uv_run(
            "uvicorn",
            "main:app",
            "--host",
            host,
            "--port",
            str(cfg.backend_port),
            "--log-level",
            "warning",
        ),
        cwd=server_dir(root),
        ready_port=cfg.backend_port,
    )


def error_block(title: str, lines: list[str]) -> None:
    """Print a multi-line ``[red]Error: ...[/]`` block, indented body.

    ``cli.colors`` is imported lazily so this module remains
    importable without ``rich``. Anything heavier (e.g., remediation
    URLs, code snippets) goes in ``lines`` -- it's rendered as plain
    ``console.print`` calls so rich BBCode in callers' strings still
    interprets.
    """
    from cli.colors import console

    console.print(f"[red]Error: {title}[/]")
    for line in lines:
        console.print(f"  {line}")
