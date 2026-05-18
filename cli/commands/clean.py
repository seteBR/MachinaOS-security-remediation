"""``machina clean`` — reset the repo to a fresh-checkout state.

Stops every process listening on the configured ports + orphaned project
processes, waits for file locks to release, then removes build artefacts
and venvs.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from cli.colors import console
from cli.config import load_config
from cli.platform_ import project_root
from cli.ports import kill_orphaned_machina_processes, kill_port


# Removed each run -- order doesn't matter, ``shutil.rmtree`` is recursive.
# Only project-local artefacts. Home-rooted state (``~/.machina/``,
# ``~/.claude/``, etc.) is the user's; we never touch it from
# ``machina clean``.
_TARGETS = [
    "node_modules",
    "client/node_modules",
    "client/dist",
    "client/.vite",
    # Python venvs
    "server/.venv",
    ".venv",             # stale root venv (should not exist)
]


# Children of ``<repo>/.machina/`` to wipe selectively. The bare
# ``.machina`` entry can't go in ``_TARGETS`` anymore because the
# ``workflows/`` subtree holds shipped example seeds (git-tracked,
# imported on first launch by ``services.example_loader``) — wiping it
# would force the operator to re-clone to recover. Anything else under
# ``.machina/`` (claude state, workspaces, credentials.db, …) is
# transient runtime state and is fair game.
_MACHINA_KEEP = frozenset({"workflows"})


def _rmtree_with_retry(path: Path, *, attempts: int = 3, delay: float = 0.1) -> bool:
    """``shutil.rmtree`` with Windows-friendly retry on file-lock errors."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return True
        except OSError as exc:
            if attempt == attempts - 1:
                console.print(f"  [yellow]Warning: Could not remove {path.name}: {exc}[/]")
                return False
            time.sleep(delay)
    return False


def clean_command() -> None:
    cfg = load_config()
    root = project_root()

    console.print("[bold]Cleaning MachinaOS...[/]\n")

    # Step 1: kill anything on configured ports
    console.print("Stopping running processes...")
    killed_ports = 0
    for port in cfg.all_ports:
        result = kill_port(port)
        if result.killed_pids:
            console.print(f"  Port {port}: Killed {len(result.killed_pids)} process(es)")
            killed_ports += len(result.killed_pids)

    # Step 2: kill orphaned project processes (may hold .venv file locks).
    # ``exclude_substring="-m cli"`` skips the supervisor running this
    # very ``clean`` command — its cmdline contains the entry-point
    # token ``-m cli``.
    orphaned = kill_orphaned_machina_processes(str(root), exclude_substring="-m cli")
    if orphaned:
        console.print(f"  Orphaned: Killed {len(orphaned)} process(es)")

    if killed_ports or orphaned:
        console.print("  Waiting for processes to release file locks...")
        time.sleep(1.0)
    else:
        console.print("  No running processes found.")

    # Step 3: remove directories
    console.print("\nRemoving directories...")
    for target in _TARGETS:
        path = root / target
        if path.exists():
            console.print(f"  Removing: {target}")
            _rmtree_with_retry(path)

    # Step 4: selectively clean ``<repo>/.machina/`` — preserve
    # ``workflows/`` (shipped example seeds, see ``_MACHINA_KEEP``);
    # wipe everything else (claude/, workspaces/, *.db, …) so the
    # repo-local DATA_DIR opt-out gets the same fresh-state treatment.
    machina_dir = root / ".machina"
    if machina_dir.is_dir():
        for child in machina_dir.iterdir():
            if child.name in _MACHINA_KEEP:
                continue
            rel = f".machina/{child.name}"
            console.print(f"  Removing: {rel}")
            if child.is_dir():
                _rmtree_with_retry(child)
            else:
                try:
                    child.unlink()
                except OSError as exc:
                    console.print(f"  [yellow]Warning: Could not remove {rel}: {exc}[/]")

    console.print("\n[green]Done.[/]")
