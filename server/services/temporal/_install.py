"""Cross-platform Temporal server binary downloader using pooch.

Downloads ``temporal-server`` + ``temporal-sql-tool`` from the
``temporalio/temporal`` GitHub releases. Pooch (https://www.fatiando.org/pooch/)
handles platform-asset resolution, SHA-256 verification, XDG-aware
cross-platform caching, archive extraction (tar.gz / zip), and
idempotent retrieval — replacing what would otherwise be ~150 LOC of
custom GitHub-release fetching with ~30 lines.

Checksums come from the release's ``checksums.txt``, queried once via
``gh release view --repo temporalio/temporal --json assets`` and pinned
below. Bump ``_VERSION`` → re-fetch checksums; pooch refuses any asset
whose SHA-256 doesn't match.
"""
from __future__ import annotations

import asyncio
import platform
import stat
from pathlib import Path

import pooch

from core.config import Settings
from core.logging import get_logger

logger = get_logger(__name__)

# Default version. Override via ``TEMPORAL_BINARY_VERSION`` env var
# (read at the start of ``_fetch_sync``). Bump together with the
# matching entry in ``_CHECKSUMS`` — pooch refuses any asset whose
# SHA-256 doesn't match the registry. Schema files bundled with the
# binary feed ``temporal-sql-tool update-schema`` so binary + schema
# versions stay in lockstep automatically.
_DEFAULT_VERSION = "1.31.0"
_BASE_URL = "https://github.com/temporalio/temporal/releases/download"


# Asset-name template — Temporal's release naming convention. The
# version slot is substituted from settings (or _DEFAULT_VERSION).
# Verified against https://github.com/temporalio/temporal/releases
_ASSET_TEMPLATES: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "temporal_{v}_linux_amd64.tar.gz",
    ("Linux", "aarch64"): "temporal_{v}_linux_arm64.tar.gz",
    ("Darwin", "x86_64"): "temporal_{v}_darwin_amd64.tar.gz",
    ("Darwin", "arm64"): "temporal_{v}_darwin_arm64.tar.gz",
    ("Windows", "AMD64"): "temporal_{v}_windows_amd64.zip",
    ("Windows", "ARM64"): "temporal_{v}_windows_arm64.zip",
}


# SHA-256 digests per release. Keyed by version → asset filename →
# digest. Bumping ``temporal_binary_version`` in Settings to a version
# not in this map raises a clear error at install time. Regenerate
# via ``gh release view --repo temporalio/temporal --json assets``.
_CHECKSUMS_BY_VERSION: dict[str, dict[str, str]] = {
    "1.31.0": {
        "temporal_1.31.0_linux_amd64.tar.gz":
            "sha256:2e1fe709f7794929691dbf7044fea8935a5af5b4686758ae6477bebdc208012b",
        "temporal_1.31.0_linux_arm64.tar.gz":
            "sha256:d02e574e2e1ee5b888b4a57d02d8438bb92d6d5eec47fcf18bf190ac594c8ed3",
        "temporal_1.31.0_darwin_amd64.tar.gz":
            "sha256:c1174e1f3ad82489bb84ab6f4fd00b82ab13cb31ca81ddf8bf449e7f5ecafdb8",
        "temporal_1.31.0_darwin_arm64.tar.gz":
            "sha256:9023d04591eb3285f31735d9298cbd6214a0627c9e71f5c7b47991c2ffd91d05",
        "temporal_1.31.0_windows_amd64.zip":
            "sha256:f4b41b3d195803a2a16bc137c2fa81af3f5bbe8044c3b033411bb19af4fdc8b8",
        "temporal_1.31.0_windows_arm64.zip":
            "sha256:a7b39728ee2d1db51877745ffda450ad0d92034f5cd429223c42438156d6af9a",
    },
}

# Names of the binaries we extract from each release tarball. The
# ``temporalio/temporal`` server release contains the cluster binaries
# only — the user-facing ``temporal`` CLI is a separate distribution
# fetched from the official URL documented at
# https://docs.temporal.io/develop/python/set-up-your-local-python:
#   - ``temporal-server`` — full cluster binary used by the postgres
#                           backend with a YAML config
#                           (``temporal-server start --config <yaml>``).
#   - ``temporal-sql-tool`` — schema migrator invoked once at boot to
#                             create + update the Postgres databases.
_BINARY_NAMES: tuple[str, ...] = ("temporal-server", "temporal-sql-tool")

# Official Temporal CLI download URL. Per the docs at
# https://docs.temporal.io/develop/python/set-up-your-local-python the
# CLI archive lives at ``temporal.download/cli/archive/latest`` with
# ``platform`` and ``arch`` query parameters. Contains a single
# ``temporal`` binary; powers ``temporal server start-dev`` (the
# sqlite/in-memory dev server) and ad-hoc workflow / operator commands.
_CLI_BASE_URL = "https://temporal.download/cli/archive/latest"
_CLI_PLATFORM_MAP: dict[tuple[str, str], tuple[str, str]] = {
    # platform.system, platform.machine -> (URL platform, URL arch)
    ("Linux", "x86_64"): ("linux", "amd64"),
    ("Linux", "aarch64"): ("linux", "arm64"),
    ("Darwin", "x86_64"): ("darwin", "amd64"),
    ("Darwin", "arm64"): ("darwin", "arm64"),
    ("Windows", "AMD64"): ("windows", "amd64"),
    ("Windows", "ARM64"): ("windows", "arm64"),
}

# pooch cache namespace. Re-used across versions; pooch's own cache
# layout includes the asset URL so versions don't collide.
_CACHE_NAMESPACE = "machinaos-temporal"


_cached: dict[str, Path] | None = None
_lock = asyncio.Lock()


def _platform_key() -> tuple[str, str]:
    key = (platform.system(), platform.machine())
    if key not in _ASSET_TEMPLATES:
        raise RuntimeError(
            f"[Temporal install] Unsupported platform: {key}. "
            f"Supported: {sorted(_ASSET_TEMPLATES.keys())}"
        )
    return key


def _asset_name(version: str) -> str:
    return _ASSET_TEMPLATES[_platform_key()].format(v=version)


def _resolver(version: str) -> pooch.Pooch:
    checksums = _CHECKSUMS_BY_VERSION.get(version)
    if checksums is None:
        raise RuntimeError(
            f"[Temporal install] No SHA-256 digests pinned for version "
            f"{version!r}. Known versions: {sorted(_CHECKSUMS_BY_VERSION.keys())}. "
            f"Add to _CHECKSUMS_BY_VERSION (see module docstring)."
        )
    return pooch.create(
        path=pooch.os_cache(_CACHE_NAMESPACE),
        base_url=f"{_BASE_URL}/v{version}/",
        registry=checksums,
    )


async def ensure_temporal_binaries(
    settings: Settings | None = None,
) -> dict[str, Path]:
    """Return ``{"temporal": Path, "temporal-server": Path, "temporal-sql-tool": Path}``.

    Two fetches, merged into one dict:
      - ``temporal-server`` + ``temporal-sql-tool`` from the pinned
        ``temporalio/temporal`` GitHub release (SHA-verified).
      - ``temporal`` CLI from the official URL at
        https://docs.temporal.io/develop/python/set-up-your-local-python
        (``temporal.download/cli/archive/latest``). No SHA pin — the
        ``latest`` URL rotates and is served over TLS.

    Idempotent — first call downloads, subsequent calls hit the pooch
    cache (XDG / OS-conventional dir). Async-locked so concurrent
    callers don't double-download. Version comes from
    ``settings.temporal_binary_version`` (env: ``TEMPORAL_BINARY_VERSION``);
    falls back to ``_DEFAULT_VERSION`` when no settings passed.
    """
    global _cached
    if settings is None:
        settings = Settings()
    version = (settings.temporal_binary_version or _DEFAULT_VERSION).lstrip("v")

    async with _lock:
        if _cached is not None:
            return _cached
        cluster_paths = await asyncio.to_thread(_fetch_sync, version)
        cli_path = await asyncio.to_thread(_fetch_cli_sync)
        _cached = {**cluster_paths, "temporal": cli_path}
        logger.info(
            "[Temporal install] binaries ready (cluster v=%s + official CLI): %s",
            version, {k: str(v) for k, v in _cached.items()},
        )
        return _cached


def _fetch_cli_sync() -> Path:
    """Download the official ``temporal`` CLI archive and return the binary path.

    Uses ``pooch.retrieve`` with ``known_hash=None`` because the
    ``temporal.download/cli/archive/latest`` URL rotates as new CLI
    versions ship — pinning a SHA would defeat the "latest" semantics
    the official docs document. TLS gives us transport integrity.
    """
    key = (platform.system(), platform.machine())
    if key not in _CLI_PLATFORM_MAP:
        raise RuntimeError(
            f"[Temporal install] Unsupported platform for CLI: {key}. "
            f"Supported: {sorted(_CLI_PLATFORM_MAP.keys())}"
        )
    url_platform, url_arch = _CLI_PLATFORM_MAP[key]
    url = f"{_CLI_BASE_URL}?platform={url_platform}&arch={url_arch}"

    is_windows = platform.system() == "Windows"
    fname = f"temporal_cli_latest_{url_platform}_{url_arch}.{'zip' if is_windows else 'tar.gz'}"
    processor = pooch.Unzip() if is_windows else pooch.Untar()

    extracted = pooch.retrieve(
        url=url,
        known_hash=None,
        path=pooch.os_cache(_CACHE_NAMESPACE),
        fname=fname,
        processor=processor,
        progressbar=True,
    )

    target = "temporal.exe" if is_windows else "temporal"
    match = next((Path(p) for p in extracted if Path(p).name == target), None)
    if match is None:
        raise RuntimeError(
            f"[Temporal install] CLI binary {target!r} not found in archive. "
            f"Extracted files: {[Path(p).name for p in extracted]}"
        )
    if not is_windows:
        mode = match.stat().st_mode
        match.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return match


def _fetch_sync(version: str) -> dict[str, Path]:
    """Synchronous pooch fetch + post-extraction binary location.

    The release tarball contains both ``temporal-server`` and
    ``temporal-sql-tool`` (plus the ``temporal`` CLI and ``tctl``) at
    the root of the archive. We extract everything via pooch's
    processor and return the names listed in ``_BINARY_NAMES``.
    """
    pup = _resolver(version)
    asset = _asset_name(version)
    processor = pooch.Unzip() if asset.endswith(".zip") else pooch.Untar()
    extracted = pup.fetch(asset, processor=processor, progressbar=True)
    suffix = ".exe" if platform.system() == "Windows" else ""

    paths: dict[str, Path] = {}
    for name in _BINARY_NAMES:
        target = f"{name}{suffix}"
        match = next((Path(p) for p in extracted if Path(p).name == target), None)
        if match is None:
            raise RuntimeError(
                f"[Temporal install] Binary {target!r} not found in {asset!r}. "
                f"Extracted files: {[Path(p).name for p in extracted]}"
            )
        paths[name] = match
        # Pooch preserves file mode on POSIX, but if the archive was
        # repacked without exec bits, ensure the binary is runnable.
        if platform.system() != "Windows":
            mode = match.stat().st_mode
            match.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return paths


__all__ = ["ensure_temporal_binaries"]


def _main() -> int:
    """Standalone entry: ``python -m services.temporal._install``.

    Used by ``machina build`` step [6/6] to materialise the Temporal
    binaries at build time instead of paying the ~90 MB download cost
    on first ``machina start``. Fetches, verifies every extracted path
    exists on disk, prints the resolved locations. Non-zero exit on
    any failure (pooch raises on SHA mismatch / network errors / asset
    missing from tarball; we add an explicit post-fetch existence pass
    so partial extractions also fail loudly).
    """
    import sys as _sys

    try:
        paths = asyncio.run(ensure_temporal_binaries())
    except Exception as exc:  # noqa: BLE001 — propagate to non-zero exit
        print(f"[Temporal install] {exc}", file=_sys.stderr)
        return 1

    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        print(
            f"[Temporal install] binaries missing after fetch: {missing}",
            file=_sys.stderr,
        )
        return 1

    for name, path in paths.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
