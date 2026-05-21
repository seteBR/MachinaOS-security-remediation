"""Postgres + Temporal server lifecycle.

Two supervisor subclasses:

  - :class:`PostgresRuntime` subclasses :class:`BaseSupervisor` directly.
    pgserver manages its own subprocess (start / stop / port binding),
    so we don't drive ``anyio.open_process`` — we just wrap its
    lifecycle in the uniform start/stop/status surface.

  - :class:`TemporalServerRuntime` subclasses :class:`BaseProcessSupervisor`.
    Fires the binary downloaded by :mod:`services.temporal._install`
    against the YAML config rendered by :mod:`services.temporal._config`.

Both use the singleton accessor pattern (``Class.get_instance()``)
from ``BaseSupervisor`` — same idiom :mod:`nodes.whatsapp._runtime`
uses for ``WhatsAppRuntime``.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Optional

from core.config import Settings
from core.logging import get_logger
from services._supervisor import BaseProcessSupervisor, BaseSupervisor
from services.temporal._config import parse_postgres_uri

logger = get_logger(__name__)

# Default Postgres port; only used as a fallback in ``PostgresRuntime.port``
# before pgserver has actually started and reported its dynamic port.
_PG_DEFAULT_PORT = 5432

# How long each TCP-readiness probe waits per attempt. Mirrors
# ``cli.tcp.probe_tcp_port``'s semantics inside the server-side
# supervisor — sub-second so a stalled subprocess fails health fast.
_PROBE_TIMEOUT_SECONDS = 1.0


async def _probe_tcp_port(port: int, host: str = "127.0.0.1") -> bool:
    """Return ``True`` iff a TCP connection to ``host:port`` succeeds
    within :data:`_PROBE_TIMEOUT_SECONDS`. Loopback-friendly readiness
    check used by both runtimes' ``health_check`` overrides. Mirrors
    :func:`cli.tcp.probe_tcp_port` but keeps server-side modules
    independent of the ``cli`` CLI package."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, OSError):
            pass
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


class PostgresRuntime(BaseSupervisor):
    """pgserver-managed PostgreSQL 16.2.

    pgserver (https://pypi.org/project/pgserver/) bundles full Postgres
    binaries cross-platform via pip and exposes a Python API for the
    process lifecycle. We wrap that API in BaseSupervisor's start/stop
    surface so the rest of the system (status broadcasts, supervisor,
    FastAPI lifespan) treats it uniformly with every other supervised
    binary.
    """

    name = "postgres"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        super().__init__()
        if settings is None:
            settings = Settings()
        self.settings = settings
        self._pg: Any = None  # pgserver.Server instance

    # ---- subclass surface (BaseSupervisor) -------------------------------

    def is_running(self) -> bool:
        return self._pg is not None

    @property
    def _data_dir(self) -> Path:
        """Env-driven pgserver data dir (``TEMPORAL_POSTGRES_SUBDIR``),
        resolved relative to ``DATA_DIR`` unless absolute."""
        return Path(self.settings._resolve_under_data(self.settings.temporal_postgres_subdir))

    async def _do_start(self) -> None:
        # Lazy import: pgserver pulls a heavy native dep tree; only
        # load it when the Postgres backend is actually selected.
        import pgserver

        data_dir = self._data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        def _start_sync() -> Any:
            return pgserver.get_server(str(data_dir), cleanup_mode=None)

        self._pg = await asyncio.to_thread(_start_sync)
        logger.info("[%s] pgserver ready at %s", self.label, self._pg.get_uri())

    async def _do_stop(self) -> None:
        pg = self._pg
        self._pg = None
        if pg is None:
            return

        def _stop_sync() -> None:
            try:
                pg.cleanup()
            except Exception as exc:  # noqa: BLE001 — best-effort shutdown
                logger.warning("[postgres] cleanup raised %r (continuing)", exc)

        await asyncio.to_thread(_stop_sync)
        logger.info("[%s] stopped", self.label)

    async def health_check(self) -> bool:
        if not self.is_running():
            return False
        # pgserver may report running before the socket is accepting;
        # use the shared TCP probe — same idiom every supervised
        # service uses for `ready_port` readiness checks.
        return await _probe_tcp_port(self.port)

    def _extra_status(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "port": self.port,
            "data_dir": str(self._data_dir),
        }

    # ---- public read-only properties -------------------------------------

    @property
    def uri(self) -> Optional[str]:
        return self._pg.get_uri() if self._pg else None

    @property
    def port(self) -> int:
        # pgserver picks a free port at start; fall back to the default
        # when called before _do_start (e.g. early status snapshots).
        if self._pg is None:
            return _PG_DEFAULT_PORT
        return parse_postgres_uri(self._pg.get_uri())["port"]


class TemporalServerRuntime(BaseProcessSupervisor):
    """Temporal server, supervised via BaseProcessSupervisor.

    Single runtime class for both backends. The only difference is
    which binary + argv we spawn and whether we run the Postgres
    schema-bootstrap step; everything else (signal / restart /
    tree-kill / health probe) is shared. Backend selected by
    ``settings.temporal_backend``:

      - ``postgres`` — spawns ``temporal-server start --config <yaml>``
        against a running :class:`PostgresRuntime` instance. YAML config
        is rendered by
        :func:`services.temporal._config.render_temporal_config`;
        schemas are migrated via
        :func:`services.temporal._config.bootstrap_temporal_schemas`.

      - ``sqlite`` — spawns ``temporal server start-dev --db-filename
        <path>`` against a SQLite file. Path comes from
        ``settings.temporal_sqlite_path`` (env-driven).

    Both binaries (``temporal``, ``temporal-server``,
    ``temporal-sql-tool``) ship in the same pooch-cached tarball
    extracted by
    :func:`services.temporal._install.ensure_temporal_binaries`, so
    swapping backends costs no extra download.

    All on-disk locations come from env-driven settings (no hardcoded
    subdirs in this module): ``settings.temporal_sqlite_path``,
    ``settings.temporal_postgres_subdir``,
    ``settings.temporal_server_subdir`` — all resolved relative to
    ``settings.data_dir`` unless already absolute.
    """

    name = "temporal"
    pipe_streams = True
    graceful_shutdown = sys.platform == "win32"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        postgres: Optional[PostgresRuntime] = None,
    ) -> None:
        super().__init__()
        if settings is None:
            settings = Settings()
        self.settings = settings
        # SIGTERM grace = settings.temporal_graceful_shutdown_seconds —
        # same knob already documented for the embedded Temporal worker.
        self.terminate_grace_seconds = float(
            settings.temporal_graceful_shutdown_seconds,
        )
        # Postgres runtime is only consulted when ``backend == "postgres"``;
        # lazy-bound there so the sqlite path doesn't spin up an unused
        # PostgresRuntime singleton or pull pgserver imports.
        self._postgres = postgres
        self._binaries: Optional[dict[str, Path]] = None
        self._config_path: Optional[Path] = None

    @property
    def backend(self) -> str:
        return self.settings.temporal_backend.strip().lower()

    @property
    def _sqlite_path(self) -> Path:
        """Env-driven SQLite db path (``TEMPORAL_SQLITE_PATH``),
        resolved relative to ``DATA_DIR`` unless absolute."""
        return Path(self.settings._resolve_under_data(self.settings.temporal_sqlite_path))

    @property
    def _server_cwd(self) -> Path:
        """Env-driven cwd subdir for the temporal-server process
        (``TEMPORAL_SERVER_SUBDIR``)."""
        return Path(self.settings._resolve_under_data(self.settings.temporal_server_subdir))

    # ---- BaseProcessSupervisor overrides ---------------------------------

    async def _pre_spawn(self) -> None:
        from services.temporal._install import ensure_temporal_binaries

        # 1. Download / cache Temporal binaries (both backends share
        #    the same tarball; pooch deduplicates across calls).
        self._binaries = await ensure_temporal_binaries(self.settings)

        if self.backend == "postgres":
            from services.temporal._config import (
                bootstrap_temporal_schemas,
                render_temporal_config,
            )

            if self._postgres is None:
                self._postgres = PostgresRuntime.get_instance(self.settings)
            if self._postgres.uri is None:
                raise RuntimeError(
                    f"[{self.label}] Postgres runtime not started; "
                    "schedule the postgres ServiceSpec before this one"
                )

            # Idempotent schema bootstrap.
            await bootstrap_temporal_schemas(
                sql_tool=self._binaries["temporal-sql-tool"],
                postgres_uri=self._postgres.uri,
                binary_path=self._binaries["temporal-server"],
            )

            # Render YAML config pointing at the Postgres URI.
            self._config_path = render_temporal_config(
                settings=self.settings,
                postgres_uri=self._postgres.uri,
            )
        else:
            # sqlite backend — ensure the parent dir for the SQLite
            # file exists before ``temporal server start-dev`` opens it.
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    def binary_path(self) -> Path:
        # ``_pre_spawn`` (called by ``BaseProcessSupervisor._do_start``
        # before this method) populates ``self._binaries`` via the
        # pooch downloader. Loud failure if that contract regresses.
        binary = "temporal-server" if self.backend == "postgres" else "temporal"
        assert self._binaries is not None, (
            f"[{self.label}] binary_path() called before _pre_spawn() "
            "populated self._binaries"
        )
        return self._binaries[binary]

    def argv(self) -> list[str]:
        if self.backend == "postgres":
            return [
                str(self.binary_path()),
                "start", "--config", str(self._config_path),
            ]

        # ``temporal server start-dev`` is the official subcommand for
        # the SQLite-backed dev server. Flags documented at
        # https://docs.temporal.io/cli/server (subset we use):
        #   --port           frontend gRPC port (gates ready-probe)
        #   --db-filename    SQLite file (omit for in-memory)
        #   --metrics-port   0 disables the Prometheus endpoint
        #   --log-level      warn keeps the supervisor log readable
        #   --ip             127.0.0.1 when TEMPORAL_BIND_LOCAL_ONLY=true
        #   --namespace      default namespace bootstrapped at start
        ip = "127.0.0.1" if self.settings.temporal_bind_local_only else "0.0.0.0"
        return [
            str(self.binary_path()), "server", "start-dev",
            "--port", str(self.settings.temporal_frontend_grpc_port),
            "--db-filename", str(self._sqlite_path),
            "--metrics-port", "0",
            "--log-level", "warn",
            "--ip", ip,
            "--namespace", self.settings.temporal_namespace,
        ]

    def cwd(self) -> Path:
        if self.backend == "postgres":
            return self._server_cwd
        # sqlite — cwd is the parent of the SQLite file so any default
        # output / log files land alongside the db rather than in the
        # supervisor's working directory.
        return self._sqlite_path.parent

    def env(self) -> dict[str, str]:
        # Temporal reads everything from YAML (postgres) or argv flags
        # (sqlite); inherit parent env only.
        return {**os.environ}

    async def health_check(self) -> bool:
        if not self.is_running():
            return False
        # gRPC frontend port — configured via
        # ``settings.temporal_frontend_grpc_port``. Same shared probe
        # MachinaOS uses for every other supervised TCP service.
        return await _probe_tcp_port(self.settings.temporal_frontend_grpc_port)

    def _extra_status(self) -> dict[str, Any]:
        base = super()._extra_status()
        extra: dict[str, Any] = {
            **base,
            "backend": self.backend,
            "grpc_port": self.settings.temporal_frontend_grpc_port,
            "binary_version": self.settings.temporal_binary_version,
        }
        if self.backend == "postgres":
            extra["config_path"] = (
                str(self._config_path) if self._config_path else None
            )
        else:
            extra["sqlite_path"] = str(self._sqlite_path)
        return extra


# ---- module-level singleton accessors -----------------------------------

def get_postgres_runtime(settings: Optional[Settings] = None) -> PostgresRuntime:
    """Return the Postgres runtime singleton."""
    return PostgresRuntime.get_instance(settings)


def get_temporal_server_runtime(
    settings: Optional[Settings] = None,
) -> TemporalServerRuntime:
    """Return the Temporal server runtime singleton."""
    return TemporalServerRuntime.get_instance(settings)


__all__ = [
    "PostgresRuntime",
    "TemporalServerRuntime",
    "get_postgres_runtime",
    "get_temporal_server_runtime",
]
