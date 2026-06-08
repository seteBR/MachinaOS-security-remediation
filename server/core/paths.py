"""Central path resolution for MachinaOs's on-disk state.

Single source of truth for every directory the app reads or writes.
The default root lives at ``~/.machina/`` — the user's home directory,
cross-platform via :meth:`pathlib.Path.home` (``$HOME`` on POSIX,
``%USERPROFILE%`` on Windows). Override with ``DATA_DIR`` env var.

Why home-rooted (not project-local): claude's auth, the WhatsApp
session DB, the credentials store, and per-workflow workspaces all
survive ``rm -rf`` of the repo. Multiple MachinaOs checkouts on the
same machine share state instead of each carrying its own copy. The
``~/.machina/`` convention matches Stripe's ``~/.config/stripe/``,
ngrok's ``~/.ngrok2/``, and claude code's own ``~/.claude/``.

Generic subtree layout under ``<DATA_DIR>/`` (= ``~/.machina/`` by
default). The module exports only generic helpers — plugin-specific
subpaths (``<DATA_DIR>/claude/``, ``<DATA_DIR>/packages/stripe/bin/``,
etc.) are composed at the plugin's call site, NOT hardcoded here.
That keeps this module from growing one helper per package:

  - :func:`data_path`      ``<DATA_DIR>/<subpath>`` — universal state-path
                            primitive every plugin composes against
  - :func:`packages_dir`   ``<DATA_DIR>/packages/`` — downloaded-binary root
  - :func:`package_dir`    ``<DATA_DIR>/packages/<name>/`` — per-service install
                            slot (callers compose further, e.g.
                            ``package_dir("claude") / "npm"``)
  - :func:`daemons_dir`    ``<DATA_DIR>/daemons/`` — supervised daemon cwds
  - :func:`workspaces_dir` ``<DATA_DIR>/workspaces/`` — per-workflow scratch
  - :func:`workspace_dir`  ``<DATA_DIR>/workspaces/<workflow_id>/``
  - :func:`example_workflows_dir` git-tracked seed JSONs at
                            ``<repo>/.machina/workflows/`` (NOT under DATA_DIR)

Reference layout once typical plugins compose against the helpers
above (Wave 14):

  - ``<DATA_DIR>/claude/``           Claude Code auth state (CLAUDE_CONFIG_DIR)
  - ``<DATA_DIR>/packages/``         Single shared MachinaOs install
    root. Holds one ``package.json`` + ``package-lock.json`` +
    ``node_modules/`` covering every MachinaOs-managed npm package
    (``@anthropic-ai/claude-code``, ``edgymeow``, ``agent-browser``).
    Each plugin's ``_install.py`` runs
    ``npm install <pkg> --prefix <packages_dir>`` to extend the tree
    idempotently — npm itself manages the dep graph.
  - ``<DATA_DIR>/packages/stripe/``    Stripe CLI binary (non-npm)
  - ``<DATA_DIR>/packages/temporal/``  Temporal CLI binary (non-npm,
                                        pooch-managed)
  - ``<DATA_DIR>/workspaces/<slug>/`` per-workflow scratch
  - ``<DATA_DIR>/daemons/``           supervised daemon cwds (shared root)
  - ``<DATA_DIR>/whatsapp/``          persistent WhatsApp session DB
  - ``<DATA_DIR>/credentials.db``     Fernet-encrypted secrets
  - ``<DATA_DIR>/workflow.db``        SQLite app DB
  - ``<DATA_DIR>/temporal.db``        Temporal server SQLite

The pre-fix layout split binaries under
:func:`platformdirs.user_cache_path` (``~/.cache/MachinaOs/`` etc.)
and Temporal under its own ``pooch.os_cache("machinaos-temporal")``
namespace — operators reported both as "not local". Daemon cwds
also used to live under ``workspaces/_<namespace>/`` and polluted
per-workflow scratch with framework state. Consolidating everything
under ``<DATA_DIR>/`` means a single ``mv ~/.machina /backup``
carries the entire MachinaOs footprint.

Out of scope: globally-installed binaries (Himalaya — system
package manager) and npm `package.json` deps managed by pnpm (none
remain after the WhatsApp migration).

Shipped example workflows live at ``<repo>/.machina/workflows/`` —
git-tracked seed JSONs auto-imported on first launch by
``services.example_loader``. The path is namespaced under ``.machina``
to share the runtime convention; the rest of ``<repo>/.machina/`` is
gitignored. ``example_workflows_dir()`` resolves to that fixed seed
location regardless of ``DATA_DIR`` — operators do NOT relocate the
shipped seeds.

Importable as ``from core.paths import data_path, package_dir,
workspace_dir, …`` so consumers never have to recompute the root
themselves (the old ``Path(__file__).resolve().parents[N] / "data"
/ ...`` idiom was duplicated across 4+ files and brittle to file
moves).

DATA_DIR resolution rules (see :func:`machina_root`):

  - Starts with ``~`` → ``Path.expanduser()`` (user home).
  - Absolute path → used verbatim.
  - Relative path → resolved under the repo root (back-compat for
    callers who set ``DATA_DIR=data`` to keep the pre-cutover layout).

Migration of pre-cutover ``<repo>/data/`` trees is the operator's
responsibility — set ``DATA_DIR`` to the legacy path (e.g.
``DATA_DIR=data``) to keep using the old layout, or move the
contents manually:

  mv server/data/claude-machina  ~/.machina/claude
  mv server/data/workspaces      ~/.machina/workspaces
  mv server/data/workflow.db     ~/.machina/workflow.db
  mv server/data/credentials.db  ~/.machina/credentials.db
"""

from __future__ import annotations

from pathlib import Path

from core.logging import get_logger

logger = get_logger(__name__)


# Repo root: server/core/paths.py -> parents[2] is the project root.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """Absolute path of the MachinaOs git repo root."""
    return _REPO_ROOT


def _resolve_data_path(base: str, subpath: str = "") -> Path:
    """Canonical state-path resolution primitive. Always returns absolute.

    Shared by :func:`data_path` (public entry point) and
    ``Settings._resolve_under_data`` (the Pydantic-side mirror used by
    state-path properties like ``credentials_db_resolved``). One
    implementation so the two never drift.

    Rules:
      - ``Path.expanduser()`` on ``base`` — no-op when no ``~`` present.
      - Absolute resolved ``base`` → used verbatim.
      - Relative ``base`` → resolved under :func:`project_root` (so
        dev mode's ``DATA_DIR=.machina`` lands at ``<repo>/.machina/``
        regardless of the subprocess's cwd).
      - Empty ``subpath`` → returns the resolved base.
      - Absolute ``subpath`` → returned verbatim.
      - Relative ``subpath`` → joined onto the resolved base.
    """
    b = Path(base).expanduser()
    if not b.is_absolute():
        b = project_root() / b
    if not subpath:
        return b.resolve()
    p = Path(subpath)
    return p.resolve() if p.is_absolute() else (b / p).resolve()


def data_path(subpath: str | Path = "") -> Path:
    """Absolute path of ``<DATA_DIR>/<subpath>``.

    Single entry point for every state location MachinaOS reads or
    writes. Reads ``Settings.data_dir`` (env var ``DATA_DIR``) — so
    the dev / daemon split (``.env.dev`` vs ``.env.template``) moves
    every state path together. Pass an empty ``subpath`` to get the
    DATA_DIR root.

    Settings is instantiated lazily — Pydantic caches the result.
    Resolution rules: see :func:`_resolve_data_path`.
    """
    from core.config import Settings

    return _resolve_data_path(Settings().data_dir, str(subpath))


def machina_root() -> Path:
    """Absolute path of the configured DATA_DIR (= ``data_path()``)."""
    return data_path()


def packages_dir() -> Path:
    """Root for binaries MachinaOs downloads on first use.

    Resolves to ``<DATA_DIR>/packages/`` — under the same operator-
    visible tree as auth state, workspaces, and daemon cwds. One
    ``mv ~/.machina`` carries every MachinaOs-managed file together,
    and one glance at ``~/.machina/`` shows the operator everything
    the app owns.

    Pre-fix this used :func:`platformdirs.user_cache_path` so binaries
    landed at ``~/.cache/MachinaOs/`` (Linux) / ``~/Library/Caches/
    MachinaOs/`` (macOS) / ``%LOCALAPPDATA%\\MachinaOs\\Cache\\``
    (Windows). Operators reported it as "not local" — the split
    between binaries (OS cache) and state (DATA_DIR) was confusing
    and the OS-cache rationale (machina clean keeps auth, cache
    wipe drops binaries) didn't matter in practice since both wipe
    operations are operator-driven anyway.

    See :func:`package_dir` for the per-service accessor.
    """
    return data_path("packages")


def package_dir(name: str) -> Path:
    """Per-service install folder under :func:`packages_dir`.

    Canonical layout — each plugin's installer (``ensure_stripe_cli``,
    ``ensure_temporal_binaries``, ``agent_browser_binary_path``, …)
    drops its tree here. Examples::

        package_dir("stripe")   -> ~/.machina/packages/stripe/
        package_dir("browser")  -> ~/.machina/packages/browser/

    Caller is responsible for ``mkdir(parents=True, exist_ok=True)``
    so this helper stays side-effect-free and safe to call during
    import-time path resolution.
    """
    return packages_dir() / name


def daemons_dir() -> Path:
    """Root for supervised event-source daemons (``stripe listen``, etc.).

    Resolves to ``<DATA_DIR>/daemons/`` — sibling of
    :func:`workspaces_dir`. Daemons are framework-owned, long-lived
    processes whose cwd is just a place to drop log / state files;
    workspaces are per-workflow scratch owned by workflow nodes
    (one subdir per ``Workflow.slug``). Conflating the two clutters
    workspaces with framework state, which is what
    ``DaemonEventSource.workdir()`` used to do before this helper
    existed.
    """
    return data_path("daemons")


def workspaces_dir() -> Path:
    """Root for per-workflow workspaces.

    Routes through ``data_path(Settings().workspace_base_dir)`` (env
    var ``WORKSPACE_BASE_DIR``) so the path stays in lockstep with
    every other state location — no hardcoded ``"workspaces"`` literal
    that drifts when the env var changes.
    """
    from core.config import Settings

    return data_path(Settings().workspace_base_dir)


def workspace_dir(workflow_id: str) -> Path:
    """Per-workflow workspace at ``<machina_root>/workspaces/<workflow_id>/``.

    The workflow executor injects this into the execution context as
    ``ctx.raw["workspace_dir"]`` and the cli_agent service splices it
    into each claude task's ``--add-dir`` so claude can read upstream
    node outputs (``fileDownloader``, ``documentParser``, code
    executors) + materialise its connected skills under
    ``<workspace_dir>/.claude/skills/``.
    """
    return workspaces_dir() / workflow_id


def example_workflows_dir() -> Path:
    """Shipped example workflow JSONs, auto-imported on first launch.

    Fixed at ``<repo>/.machina/workflows/`` — these are git-tracked
    seed JSONs that ship with the repo (see ``services.example_loader``
    for the import flow). The path is intentionally NOT under
    :func:`machina_root` because the seeds must survive ``machina
    clean`` (which wipes the rest of ``.machina/``) and must be the
    same location regardless of the operator's ``DATA_DIR`` setting.
    """
    return project_root() / ".machina" / "workflows"


__all__ = [
    "project_root",
    "machina_root",
    "data_path",
    "packages_dir",
    "package_dir",
    "daemons_dir",
    "workspaces_dir",
    "workspace_dir",
    "example_workflows_dir",
]
