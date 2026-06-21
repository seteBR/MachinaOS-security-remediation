# Docker Deployment

This profile runs MachinaOS as one container:

- FastAPI serves the API, WebSocket, and built React app on `PORT`.
- The Node.js JavaScript/TypeScript executor runs inside the same container
  bound to `127.0.0.1:3020`.
- Persistent state lives in the `machinaos-data` Docker volume mounted at
  `/data`.

## First Deploy

```bash
cp .env.production.example .env.production
# edit .env.production and rotate secrets/passwords
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production logs -f machinaos
```

For an internal-only LAN bind, set for example:

```env
MACHINAOS_BIND=172.24.102.180
MACHINAOS_PORT=3010
CORS_ORIGINS=["http://172.24.102.180:3010"]
```

Do not expose this directly to the public internet until runtime tool-risk
allowlists are enforced.

## Update

```bash
git pull --ff-only
docker compose --env-file .env.production up -d --build
```

## GitHub Actions Deploy

The production deploy workflow runs on the DockerDeployment self-hosted runner
with labels `machinaos` and `docker-deployment`.

Keep the private production env file on the VM:

```bash
install -m 600 .env.production /home/felipe/machinaos-production.env
```

Then run **Deploy Docker** from GitHub Actions, or let it run after the `CI`
workflow succeeds on `main`.

## Backup

```bash
docker run --rm -v machinaos-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/machinaos-data-$(date +%Y%m%d-%H%M%S).tgz -C /data .
```
