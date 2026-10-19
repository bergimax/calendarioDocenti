# Deployment

| Environment | URL | Trigger | Gate |
|---|---|---|---|
| dev | local `make up` / CI-built images | every merge to `master` (CD job `deploy-dev`) | CI green |
| production | https://130-110-14-231.sslip.io | `deploy-prod` job | **manual approval** (GitHub `production` environment) |

Pipeline: `.github/workflows/ci.yml` (tests on every PR and push) →
`.github/workflows/cd.yml` (build images, deploy dev automatically, production after
approval). Production host: Oracle Cloud Always Free VM running `docker compose`
with Caddy for HTTPS; helper scripts and the step-by-step setup are in
[`deploy/README.md`](../deploy/README.md) (backups: `deploy/backup-db.sh`).

Rollback: redeploy the previous image tag (`IMAGE_TAG=<sha>`), see the CD workflow.
