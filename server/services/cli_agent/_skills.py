"""Skill materialisation helper shared by pool + non-pool claude paths.

Writes ``<cwd>/.claude/skills/<name>/SKILL.md`` for each connected skill
so the spawned claude can invoke them via its built-in ``Skill`` tool
(when ``--allowedTools`` includes ``Skill``). The
``AnthropicClaudeProvider.interactive_argv`` adds ``Skill`` to the
allowlist iff ``connected_skill_names`` is non-empty — so this helper
and the conditional allowlist entry are paired.

Two skill shapes:

  - **Filesystem skills** (``server/skills/<group>/<name>/SKILL.md``):
    copied wholesale via ``shutil.copytree`` so ``scripts/`` and
    ``references/`` survive.
  - **Database skills** (user-created from the UI): reconstructed from
    frontmatter — ``name``, ``description``, ``allowed-tools``,
    ``metadata`` — plus the markdown body.

This used to live as an instance method on ``AICliSession``; the pool
path didn't call it. Extracted to a module-level free function so both
``AICliSession._pre_spawn`` (non-pool, PTY-driven) and
``ClaudeSessionPool._spawn`` (pool, subprocess+stream-json) call the
same code with the same semantics.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

import yaml

from core.logging import get_logger

logger = get_logger(__name__)


async def materialise_skills(
    cwd: Path,
    skill_names: Iterable[str],
    *,
    log_label: str = "cli-agent",
) -> int:
    """Write SKILL.md trees under ``<cwd>/.claude/skills/`` for each name.

    Returns the number of skills successfully written. Failures (skill
    not found, OSError on copy / write) log at WARNING and are skipped
    — never fatal to the spawn.

    Args:
        cwd: Spawn directory. Memory-bound runs pass ``repo_root``;
            non-memory runs pass the per-task git worktree. Either way
            the helper writes under ``<cwd>/.claude/skills/<name>/``.
        skill_names: The set of skill names to materialise. Caller is
            responsible for passing only the skills wired through
            the agent's ``input-skill`` handle.
        log_label: Free-form prefix shown in log lines. Defaults to
            ``"cli-agent"``; callers pass ``self.label`` for sessions
            and ``f"pool {memory_node_id}"`` for the pool path.
    """
    skill_list = [s for s in skill_names if s]
    if not skill_list:
        return 0

    # Lazy import — the skill loader pulls the YAML parser + sqlmodel
    # which we don't want to charge on module import.
    from services.skill_loader import get_skill_loader

    loader = get_skill_loader()
    skills_dir = Path(cwd) / ".claude" / "skills"
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "[%s] cannot create skills dir %s: %s — skipping materialisation",
            log_label, skills_dir, exc,
        )
        return 0

    written = 0
    for name in skill_list:
        try:
            skill = await loader.load_skill_async(name)
        except Exception as exc:
            logger.warning(
                "[%s] load_skill_async(%r) failed: %s",
                log_label, name, exc,
            )
            continue
        if skill is None:
            logger.warning(
                "[%s] skill %r not found — skipping materialisation",
                log_label, name,
            )
            continue

        dest = skills_dir / name
        try:
            if skill.metadata.path is not None:
                # Filesystem skill: copy whole directory tree so
                # `scripts/` + `references/` survive intact.
                shutil.copytree(skill.metadata.path, dest, dirs_exist_ok=True)
            else:
                # DB skill: reconstruct frontmatter + body.
                dest.mkdir(parents=True, exist_ok=True)
                frontmatter = {
                    "name": skill.metadata.name,
                    "description": skill.metadata.description,
                    "allowed-tools": " ".join(skill.metadata.allowed_tools),
                    "metadata": skill.metadata.metadata,
                }
                body = (
                    f"---\n"
                    f"{yaml.safe_dump(frontmatter, sort_keys=False)}"
                    f"---\n\n"
                    f"{skill.instructions}"
                )
                (dest / "SKILL.md").write_text(body, encoding="utf-8")
            written += 1
            logger.info(
                "[%s] materialised skill %r -> %s", log_label, name, dest,
            )
        except OSError as exc:
            logger.warning(
                "[%s] failed to materialise skill %r at %s: %s",
                log_label, name, dest, exc,
            )

    return written
