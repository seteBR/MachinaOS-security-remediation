# Security Policy

This repository is a public security-hardened snapshot of
[`zeenie-ai/MachinaOS`](https://github.com/zeenie-ai/MachinaOS). The current
supported branch for this snapshot is `main`.

## Reporting a Vulnerability

Use GitHub private vulnerability reporting when it is available on this
repository. If private reporting is not available, open a minimal public issue
asking for a private contact path and do not include exploit details, secrets,
proof-of-concept payloads, logs, or data from third-party systems.

Please include, privately:

- Affected commit, branch, version, or deployment mode.
- A short description of the impact.
- Reproduction steps or a proof of concept, when safe to share.
- Whether the issue also appears to affect upstream MachinaOS.

If the issue affects the upstream project, report it to
[`zeenie-ai/MachinaOS`](https://github.com/zeenie-ai/MachinaOS) as well.

## Scope

Security reports are in scope when they affect this repository's supported
runtime, packaging, or documented deployment paths, including:

- Authentication bypasses and unsafe public-bind defaults.
- Webhook, MCP, or API exposure issues.
- Prompt injection, tool injection, or agent-context exfiltration paths.
- Secret handling, logging, or accidental publication risks.
- Executor sandbox escapes or denial-of-service vectors.
- Dependency vulnerabilities in supported JavaScript or Python dependency trees.
- Telemetry, privacy, or unexpected network-behavior concerns.

Reports about unsupported forks, local-only experimental changes, or systems
outside this repository may be redirected to the relevant maintainer.

## Disclosure Expectations

Do not publicly disclose exploit details until maintainers have had a reasonable
opportunity to investigate and release a fix. Avoid testing against systems you
do not own or have explicit permission to assess.

## Maintainer Checks

Before publishing security-sensitive changes, maintainers should run:

```sh
pnpm audit --prod
npm audit --omit=dev --prefix server
uvx pip-audit -r server/requirements.txt
uv run --project server pytest server/tests/test_webhook_security.py server/tests/test_trigger_listener_workflow.py server/tests/nodes/test_code_fs_process.py::TestPythonExecutor -q
uv run --with typer --with rich --with anyio --with psutil --with platformdirs --with pytest python -m pytest cli/tests/test_start.py cli/tests/test_dev.py -q
```
