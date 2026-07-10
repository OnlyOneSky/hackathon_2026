# Runbook — bring the whole demo up on a different computer

Everything travels in git, including `taiga-backup/` (demo-grade secrets,
private repo — owner's call). One exception: the **Slack bot token** is
redacted from `taiga-backup/loophub.env` (GitHub push protection blocks it);
re-paste it into `loopHub/.env` on the new machine from api.slack.com/apps.

Two paths: **A. Restore the exact current board** (recommended — keeps all
cards/history/timings) or **B. Fresh provision** (blank boards; follow
`loopHub/SETUP.md` instead).

## What's in taiga-backup/ (copied manually)

| File | What |
|---|---|
| `taiga-db.sql` | full Postgres dump — all 3 boards, cards, comments, webhooks, users (taken 2026-07-10 17:14) |
| `taiga-media.tar.gz` | Taiga media volume (avatars/attachments) |
| `taiga-docker.env` | the `.env` for taiga-docker — **SECRET_KEY must match the DB dump**, do not regenerate |
| `loophub.env` | loop-hub's `.env` (webhook secret, loop-bot creds, Slack channel) — **Slack token is redacted** (GitHub push protection); re-paste it from api.slack.com/apps after copying |
| `DEMO-CREDENTIALS.md` | all logins/URLs in one sheet |

## Path A — restore (≈30 min, mostly downloads)

### 1. Prerequisites
Docker Desktop, Python 3.11+, `uv`, Node 20+, git, and an **authenticated
`claude` CLI** (`claude login`; verify: `claude -p "reply ok" --model haiku`).

### 2. Clone the three repos
```bash
cd ~/Workspace/Projects        # or wherever — but then fix the paths in step 5
git clone https://github.com/OnlyOneSky/hackathon_2026.git "Hackathon 2026"
cd "Hackathon 2026"
git checkout claude/loop-hub-build-plan-d95b4d   # loopHub lives on this branch
git clone git@github.com:OnlyOneSky/loopEngineer.git loopEngineer
git clone https://github.com/OnlyOneSky/hackDemo.git ../hackDemo
(cd ../hackDemo && npm ci)
```

### 3. Taiga with restored data
```bash
git clone https://github.com/taigaio/taiga-docker && cd taiga-docker
cp ../taiga-backup/taiga-docker.env .env          # keeps the matching SECRET_KEY
# enable webhooks in docker-compose.yml (x-environment anchor):
#   WEBHOOKS_ENABLED: "True"
#   WEBHOOKS_ALLOW_PRIVATE_ADDRESS: "True"
# (Linux only: add extra_hosts: ["host.docker.internal:host-gateway"] to taiga-back)
docker compose up -d taiga-db && sleep 15
docker compose exec -T taiga-db psql -U taiga -c "DROP DATABASE IF EXISTS taiga WITH (FORCE)" postgres
docker compose exec -T taiga-db psql -U taiga -c "CREATE DATABASE taiga" postgres
docker compose exec -T taiga-db psql -U taiga taiga < ../taiga-backup/taiga-db.sql
docker run --rm -v taiga-docker_taiga-media-data:/media \
  -v "$PWD/../taiga-backup":/backup alpine tar xzf /backup/taiga-media.tar.gz -C /media
docker compose up -d
```
**Verify:** http://localhost:9000 → log in `admin` (password in
DEMO-CREDENTIALS.md) → all three boards and every card/comment are there.

### 4. loop-hub
```bash
cd ../loopHub          # (inside the hackathon repo, on the branch)
cp ../taiga-backup/loophub.env .env
```

### 5. Fix machine-specific absolute paths (the one manual chore)
- `loopHub/repos.toml` — every `url` (loopEngineer demo repos + hackDemo clone)
- `loopHub/hub/app.py` — `DEFAULT_CONSTITUTION`
- `loopHub/hub/loop_runner.py` — `LOOPENGINE_ROOT`

### 6. Start and verify
```bash
set -a; source .env; set +a
uv run --with fastapi --with uvicorn --with httpx python -m hub    # port 8400
```
Startup must log `resolved status ids` for projects 1/2/3 (it re-mints the
loop-bot token from credentials, so nothing expires). Then the 60-second smoke
test: on the **Kanban view**, drag a *story* with `repo` set into Spec
Drafting → red `ai-drafting` tag appears → spec lands → card auto-moves to
Spec Review → Slack ping.

### 7. Demo assets
- Demo script + measured timings: `loopEngineer/docs/DEMO-RUNBOOK.md` (board-driven section)
- Angular site: `cd ../hackDemo && npx ng serve` → http://localhost:4200
- Story #40's sign-out branch `loop/20260710T032634-e2195c` is still unmerged
  (that's the human gate — merge it live in the demo if you like)

## Path B — fresh provision
Follow `loopHub/SETUP.md` top to bottom (creates blank boards with the right
columns via script). Use this if you don't care about existing cards.

## Known gotchas (all hit and solved once already)
| Symptom | Fix |
|---|---|
| Cards don't react to drags | You dragged a **task** on the sprint taskboard — drag the **story** on the Kanban view; tasks have separate statuses and are not wired |
| Story won't drag on Kanban | Check it's not closed (Done) and you're not filtering; worst case open the story and change Status in the detail panel — same webhook fires |
| Webhooks silently stop | `docker restart taiga-docker-taiga-async-1` (the async worker delivers webhooks and can wedge if the hub was down) |
| 401s in hub log | Token expired mid-session — restart loop-hub; startup re-mints from credentials |
| Move made while hub was down | Do nothing; the reconciliation poller re-enqueues it within 60 s |
| Docker restarted | `docker compose up -d` in taiga-docker/, then restart loop-hub (volumes persist) |
