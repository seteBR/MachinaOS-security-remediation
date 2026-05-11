# CI/CD Pipeline

Internal reference for the GitHub Actions CI/CD pipeline. Covers all workflows, the shared composite action, predeploy validation, release publishing, and documentation deployment.

---

## Overview

```
                          +------------------+
  push to main ---------> |     ci.yml       |---+
  PR to main -----------> |                  |   |
                          +------------------+   |
                                                 |    +--------------------+
  PR to main (Dockerfile +------------------+    +--> |  predeploy.yml     |
  or compose changes) --> | docker-build.yml |---+--> |  (reusable)        |
                          +------------------+   |    |                    |
                                                 |    | - build-and-lint   |
  v*.*.* tag push ------> +------------------+  |    | - docker-build     |
  GitHub release -------> |   release.yml    |---+    | - docker-compose   |
  manual dispatch ------> |                  |        | - test-install     |
                          |  +-- predeploy --+        +--------------------+
                          |  |
                          |  +-- publish-npm ---------> npmjs.org (machina)
                          |  +-- publish-github-pkgs -> GitHub Packages (@zeenie-ai/machina)
                          +------------------+

  push to docs-MachinaOs/ +------------------+
  manual dispatch ------> |    docs.yml      |-------> Mintlify (docs site)
                          +------------------+
```

### Workflow Summary

| Workflow | File | Triggers | Purpose |
|----------|------|----------|---------|
| CI | `.github/workflows/ci.yml` | Push to main, PRs to main | Validate every code change via predeploy |
| Docker Build | `.github/workflows/docker-build.yml` | PRs to main (Dockerfile/compose changes) | Validate Docker-specific changes via predeploy |
| Release | `.github/workflows/release.yml` | `v*.*.*` tags, GitHub releases, manual | Predeploy gate then publish to npm + GitHub Packages |
| Deploy Docs | `.github/workflows/docs.yml` | Push to `docs-MachinaOs/**` on main, manual | Deploy Mintlify documentation |
| Predeploy | `.github/workflows/predeploy.yml` | Called by other workflows (`workflow_call`) | Reusable validation: build, lint, Docker, cross-platform install |
| Setup Action | `.github/actions/setup/action.yml` | Used as composite action step | Shared Node.js + Python + uv environment setup |

### Required Secrets

| Secret | Used By | Description |
|--------|---------|-------------|
| `NPM_TOKEN` | release.yml | npm registry authentication for publishing |
| `GITHUB_TOKEN` | release.yml | GitHub Packages authentication (auto-provided by Actions) |
| `MINTLIFY_TOKEN` | docs.yml | Mintlify documentation deployment token |

---

## Composite Setup Action

**File:** `.github/actions/setup/action.yml`

Shared environment setup used by `predeploy.yml` jobs. Eliminates duplicated Node/Python/uv installation across workflows.

```yaml
# Usage in workflow steps:
- uses: ./.github/actions/setup
- uses: ./.github/actions/setup
  with:
    node-version: '22'
```

### What It Installs

| Tool | Default Version | Action Used |
|------|----------------|-------------|
| Node.js | 20 | `actions/setup-node@v4` (with npm cache) |
| Python | 3.12 | `actions/setup-python@v5` |
| uv | latest | `astral-sh/setup-uv@v4` |

### Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `node-version` | `'20'` | Node.js version to install |
| `python-version` | `'3.12'` | Python version to install |

Python and uv are needed because `postinstall.js` skips Python venv setup in CI, so they must be available for the `machina build` command in `test-install`.

---

## Predeploy Validation

**File:** `.github/workflows/predeploy.yml`

The core reusable workflow. Triggered via `workflow_call` by `ci.yml`, `docker-build.yml`, and `release.yml`. Contains 4 jobs -- `build-and-lint`, `docker-build`, and `test-install` run in parallel; `docker-compose-test` depends on `docker-build`.

### Job: build-and-lint

Validates that the full project builds and the client passes linting.

| Step | Command | Description |
|------|---------|-------------|
| Checkout | `actions/checkout@v4` | Clone repo |
| Setup environment | `./.github/actions/setup` | Install Node.js 20, Python 3.12, uv |
| Build all services | `npm run build` | Full production build |
| Lint client | `cd client && npm run lint` | ESLint/TypeScript validation |

### Job: docker-build

Validates all 3 Docker images build successfully. Uses Docker Buildx with GitHub Actions cache for layer reuse.

| Image | Context | Dockerfile | Notes |
|-------|---------|------------|-------|
| Frontend | `./client` | `./client/Dockerfile` | Multi-stage build, `target: production` |
| Backend | `./server` | `./server/Dockerfile` | Python 3.12-slim |
| WhatsApp | `./docker` | `./docker/Dockerfile.whatsapp` | Node.js 20-alpine with whatsapp-rpc |

All builds use:
- `docker/setup-buildx-action@v3`
- `docker/build-push-action@v6`
- `push: false` (validation only, no registry push)
- `cache-from: type=gha` / `cache-to: type=gha,mode=max` (GitHub Actions layer cache)

### Job: docker-compose-test

**Depends on:** `docker-build`

Full-stack smoke test using the production Docker Compose configuration.

**Steps:**
1. Create `.env` from `.env.template`
2. Build with `docker compose -f docker-compose.prod.yml build`
3. Start services with `docker compose -f docker-compose.prod.yml up -d`
4. Health check loop (30 retries, 2s interval = 60s max):
   - Backend: `curl -sf http://localhost:3010/health`
   - Frontend: `curl -f http://localhost:3000`
   - Print `docker compose ps` on success
5. On failure: dump all container logs
6. Always: `docker compose -f docker-compose.prod.yml down -v` (cleanup)

### Job: test-install

Cross-platform npm package installation and CLI validation.

**Matrix:**

| Axis | Values |
|------|--------|
| OS | `ubuntu-latest`, `macos-latest`, `windows-latest` |
| Node.js | 20, 22 |

Total: **6 combinations**, `fail-fast: false` (all run regardless of individual failures).

**Steps:**
1. Checkout
2. Setup environment (composite action with matrix `node-version`)
3. `npm pack` -- create tarball
4. `npm install -g machina-*.tgz` -- global install from tarball
5. `machina --help` -- verify CLI is available
6. `machina build` -- install client deps, build client, setup Python venv
7. Verify build artifacts exist at `$(npm root -g)/machina`:
   - `.env` file
   - `client/dist/` directory
   - `server/.venv/` directory
8. `machina start &` -- start in background, wait 10s, verify process is still running

All steps use `shell: bash` for cross-platform compatibility (Windows uses Git Bash).

---

## CI Workflow

**File:** `.github/workflows/ci.yml`

Thin wrapper that delegates all validation to `predeploy.yml`.

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  predeploy:
    uses: ./.github/workflows/predeploy.yml
```

Every push to main and every PR targeting main runs the full predeploy suite (build, lint, Docker, cross-platform install).

---

## Docker Build Workflow

**File:** `.github/workflows/docker-build.yml`

Scoped validation for Docker-related changes. Only triggers when specific files are modified in a PR.

```yaml
on:
  pull_request:
    branches: [main]
    paths:
      - 'client/Dockerfile'
      - 'server/Dockerfile'
      - 'docker/Dockerfile.whatsapp'
      - 'docker-compose*.yml'
```

Delegates to `predeploy.yml`. Dockerfile changes in PRs get validated by both `ci.yml` (always runs on PRs) and `docker-build.yml` (path-scoped). The reusable workflow pattern and GHA caching make this overlap low-cost.

---

## Release Workflow

**File:** `.github/workflows/release.yml`

Publishes the npm package after predeploy validation passes.

### Triggers

| Trigger | Condition |
|---------|-----------|
| Push tags | `v*.*.*` (e.g., `v1.0.0`, `v2.3.1`) |
| Release | GitHub release published |
| Manual | `workflow_dispatch` |

### Job: predeploy (gate)

Calls `predeploy.yml` as a prerequisite. Both publish jobs require this to pass (`needs: predeploy`).

### Job: publish-npm

Publishes the unscoped `machina` package to the public npm registry.

```
npm install --ignore-scripts  # Install deps without running postinstall
npm pack --dry-run             # Verify package contents
npm publish --access public    # Publish to npmjs.org
```

Uses `NODE_AUTH_TOKEN` from `secrets.NPM_TOKEN`. Registry URL: `https://registry.npmjs.org`.

### Job: publish-github-packages

Publishes the scoped `@zeenie-ai/machina` package to GitHub Packages.

Requires `packages: write` permission. Before publishing, an inline Node.js script rewrites `package.json`:

```javascript
// Executed at build time to scope the package name:
const pkg = require('./package.json');
pkg.name = '@zeenie-ai/machina';
pkg.publishConfig = { registry: 'https://npm.pkg.github.com' };
require('fs').writeFileSync('package.json', JSON.stringify(pkg, null, 2));
```

Then publishes via `npm publish` with `GITHUB_TOKEN` as auth token. Registry URL: `https://npm.pkg.github.com`.

---

## Docs Workflow

**File:** `.github/workflows/docs.yml`

Deploys the Mintlify documentation site when docs change.

### Triggers

| Trigger | Condition |
|---------|-----------|
| Push | Changes to `docs-MachinaOs/**` on main branch |
| Manual | `workflow_dispatch` |

### Steps

1. Checkout repo
2. Setup Node.js 20
3. `npm install -g mintlify` -- install Mintlify CLI
4. `mintlify deploy` -- deploy docs (working directory: `docs-MachinaOs`)

Uses `MINTLIFY_TOKEN` secret for authentication.

---

## Workflow Dependency Graph

```
+------------------+        +---------------------+
|     ci.yml       |------->|                     |
| (push/PR main)   |        |   predeploy.yml     |
+------------------+        |   (workflow_call)    |
                            |                     |
+------------------+        |  +-- build-and-lint  |
| docker-build.yml |------->|  +-- docker-build    |
| (PR, Dockerfiles)|        |  +-- compose-test    |
+------------------+        |  +-- test-install    |
                            |                     |
+------------------+        +---------------------+
|   release.yml    |------->|         |
| (tags, releases) |        |         v
+------------------+        |  +-- publish-npm
                            |  +-- publish-github-packages
                            +---------------------+

+------------------+
|    docs.yml      |------> Mintlify deployment
| (docs-MachinaOs/)|        (independent pipeline)
+------------------+
```

### Key Design Decisions

- **Reusable `predeploy.yml`**: Single source of truth for validation logic. All entry-point workflows delegate to it, avoiding duplication.
- **Composite setup action**: Node.js, Python, and uv installation centralized in `.github/actions/setup/action.yml`. Workflows pass version overrides as inputs.
- **`fail-fast: false` in test-install**: All 6 OS/Node combinations run to completion, giving visibility into platform-specific failures even when one platform fails.
- **Docker layer caching via GHA**: `cache-from: type=gha` reuses layers across runs, reducing Docker build times.
- **Scoped `docker-build.yml`**: Prevents full Docker rebuild on every PR -- only triggers when Dockerfile or compose files change.
- **Dual npm publish**: Unscoped `machina` for public npm, scoped `@zeenie-ai/machina` for GitHub Packages. The scoped name is rewritten at publish time, not in source.

---

## Source Files

| File | Lines | Description |
|------|-------|-------------|
| `.github/workflows/ci.yml` | 15 | CI entry point, delegates to predeploy |
| `.github/workflows/predeploy.yml` | 157 | Reusable validation (build, lint, Docker, install) |
| `.github/workflows/release.yml` | 73 | Predeploy gate + dual npm publish |
| `.github/workflows/docker-build.yml` | 18 | Docker-scoped PR validation |
| `.github/workflows/docs.yml` | 33 | Mintlify documentation deployment |
| `.github/actions/setup/action.yml` | 37 | Composite action: Node.js + Python + uv |
