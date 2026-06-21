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

For a network-restricted bind, set the host-side bind address to a private
interface IP, for example:

```env
MACHINAOS_BIND=<private-interface-ip>
MACHINAOS_PORT=3010
CORS_ORIGINS=["http://<private-interface-ip>:3010"]
```

Do not expose this directly to the public internet until runtime tool-risk
allowlists are enforced.

## Update

```bash
git pull --ff-only
docker compose --env-file .env.production up -d --build
```

## CI/CD Deploy

Do not attach a persistent self-hosted GitHub Actions runner with Docker access
to this public repository. Keep production deployment automation in a private
infra repository, or use a pull-based deploy service on the Docker host that
only fetches trusted refs after review.

Keep the private production env file outside this public repository:

```bash
install -m 600 .env.production <private-env-path>
```

That private deploy automation can then run:

```bash
git pull --ff-only
docker compose --env-file .env.production up -d --build
curl -fsS http://<private-interface-ip>:3010/health
```

## Backup

```bash
docker run --rm -v machinaos-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/machinaos-data-$(date +%Y%m%d-%H%M%S).tgz -C /data .
```
