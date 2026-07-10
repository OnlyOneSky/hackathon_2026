# Demo credentials & endpoints (NOT committed — listed in .gitignore)

Everything is demo-grade, single-machine only. Created 2026-07-09.

## Endpoints

| Service | URL | Notes |
|---|---|---|
| Taiga UI/API | http://localhost:9000 | taiga-docker compose stack |
| loop-hub | http://localhost:8400 | `/healthz`, `/webhooks/taiga` |

## Taiga accounts

| Account | Username | Password | Purpose |
|---|---|---|---|
| Superuser | `admin` | `adminloop2026` | UI login, project admin, demo "reviewer" (阿哲) |
| Bot | `loop-bot` | `loopbot2026` | loop-hub write-backs; member of all 3 projects (role: Back) |

## Secrets in `loopHub/.env`

| Key | What |
|---|---|
| `TAIGA_ADMIN_PASSWORD` | admin password (above) |
| `LOOPHUB_WEBHOOK_SECRET` | shared secret on all 3 project webhooks (random hex) |
| `LOOPHUB_TAIGA_TOKEN` | loop-bot auth token; re-mint if expired: `python -c "from hub.taiga import auth_token; print(auth_token('http://localhost:9000','loop-bot','loopbot2026'))"` |

## Other secrets

- `taiga-docker/.env` — `SECRET_KEY` and `POSTGRES_PASSWORD` (random hex, only Taiga uses them).
- No GitHub PAT: demo uses local repo clones (`repos.toml`), no remote pushes.
- LLM access: the host's authenticated `claude` CLI (no API key stored anywhere).

## Taiga project ids (match repos.toml)

"Angular Frontend"=1 (team key `angular-frontend`, includes `hackdemo` →
local clone at /Users/jeffchen/Workspace/Projects/hackDemo, pushed to
https://github.com/OnlyOneSky/hackDemo) · lending-board=2 · cards-board=3

Columns (all boards): To-Do / Spec Drafting / Spec Review / Dev / PR / Done
