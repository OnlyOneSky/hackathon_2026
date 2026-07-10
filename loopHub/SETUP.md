# Full demo setup — from a blank computer to a working board-driven loop

This is the complete preparation guide: every component, in install order, with
a verification step after each so you never debug two layers at once (the same
principle the build followed: prove each connector standalone before wiring).

Secrets and passwords are NOT in this file — see `DEMO-CREDENTIALS.md`
(gitignored, machine-local). When you set up a new machine you will create a
new copy of it as you go.

---

## 0. Prerequisites (~15 min, needs internet)

| Tool | Install | Verify |
|---|---|---|
| Docker Desktop | docker.com download | `docker info` prints a server version |
| Python 3.11+ | `brew install python` | `python3 --version` |
| uv | `brew install uv` | `uv --version` |
| claude CLI | `npm i -g @anthropic-ai/claude-code`, then `claude login` | `claude -p "reply ok" --model haiku` prints `ok` |
| git | ships with Xcode CLT | `git --version` |

The `claude` CLI must be **authenticated on the host** — both the Spec agent
and the dev loop shell out to it. (`codex` is optional; the loop defaults to
`--agent claude`.)

## 1. Get the code

```bash
git clone <hackathon-repo-url> "Hackathon 2026" && cd "Hackathon 2026"
# loopEngineer/ is its own repo (gitlink) — clone/copy it into place too:
git clone <loopengineer-repo-url> loopEngineer
```

**⚠️ Absolute paths to edit on a new machine.** Three files carry paths that
must point at the new machine's checkout:

1. `loopHub/repos.toml` — every repo `url` (the loopEngineer demo repos AND
   the `hackdemo` entry, which points at a local clone of
   https://github.com/OnlyOneSky/hackDemo — clone it too: it needs Node 20+
   and `npm ci`).
2. `loopHub/hub/app.py` — `DEFAULT_CONSTITUTION` (path to
   `loopEngineer/skills/constitution.md`).
3. `loopHub/hub/loop_runner.py` — `LOOPENGINE_ROOT`.

(Yes, this should become an env var / config key — hackathon shortcut.)

**Verify loopEngineer standalone** before anything board-related:

```bash
cd loopEngineer
python3 -m venv .venv && .venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q      # all green (1 skip is fine)
```

## 2. Taiga (the board)

```bash
cd "Hackathon 2026"
git clone https://github.com/taigaio/taiga-docker && cd taiga-docker
```

Edit **`.env`**: set `SECRET_KEY` and `POSTGRES_PASSWORD` to fresh random
values (`openssl rand -hex 24`), `ENABLE_TELEMETRY=False`. Keep
`TAIGA_DOMAIN=localhost:9000` for a laptop demo (set it to the machine's IP if
judges browse from their own devices).

Edit **`docker-compose.yml`** — in the `x-environment` anchor shared by
taiga-back/taiga-async add:

```yaml
  WEBHOOKS_ENABLED: "True"
  WEBHOOKS_ALLOW_PRIVATE_ADDRESS: "True"   # demo only; host.docker.internal is private
```

> Do NOT use `WEBHOOKS_BLOCK_PRIVATE_ADDRESS` — that variable does not exist.
> Symptom of getting this wrong: card moves work but webhook logs show
> `error-in-request: Private IP Address not allowed`.
> On Linux, also add `extra_hosts: ["host.docker.internal:host-gateway"]` to
> taiga-back.

Launch and create the superuser (pick a password; record it in
DEMO-CREDENTIALS.md):

```bash
docker compose up -d          # first pull ~3-4 GB, several minutes
docker compose exec -T \
  -e DJANGO_SUPERUSER_USERNAME=admin \
  -e DJANGO_SUPERUSER_EMAIL=admin@example.com \
  -e DJANGO_SUPERUSER_PASSWORD=<pick-one> \
  taiga-back python manage.py createsuperuser --noinput
```

**Verify:** http://localhost:9000 loads and admin can log in.

## 3. Bot account

```bash
docker compose exec -T taiga-back python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
u, _ = U.objects.get_or_create(username='loop-bot', defaults=dict(email='loop-bot@example.com', full_name='Loop Bot'))
u.set_password('<pick-one>'); u.is_active=True; u.save()"
```

## 4. loop-hub secrets file

```bash
cd ../loopHub
cat > .env <<EOF
TAIGA_ADMIN_PASSWORD=<superuser password>
LOOPHUB_WEBHOOK_SECRET=$(openssl rand -hex 16)
EOF
```

## 5. Provision the board (idempotent script)

Creates 3 projects (Angular Frontend / lending / cards), the 6 columns
(`To-Do / Spec Drafting / Spec Review / Dev / PR / Done` — these names must
match `config.toml` exactly; loop-hub fails loudly at startup otherwise), the
required `repo` custom attribute, and the webhook →
`http://host.docker.internal:8400/webhooks/taiga`:

```bash
set -a; source .env; set +a
uv run --with httpx python scripts/m1_board_setup.py
```

It prints the three project ids — put them into `repos.toml`
(`taiga_project = …`). Fresh install order gives 1/2/3.

Then add loop-bot to each project and mint its token:

```bash
# membership (role "Back") — one-liner per project id, or reuse the snippet in README
uv run --with httpx python - <<'EOF'
import os, httpx
BASE="http://localhost:9000"
a = httpx.post(f"{BASE}/api/v1/auth", json={"type":"normal","username":"admin","password":os.environ["TAIGA_ADMIN_PASSWORD"]}).json()
c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {a['auth_token']}"})
for pid in (1,2,3):
    role = c.get("/api/v1/roles", params={"project":pid}).json()[0]
    print(pid, c.post("/api/v1/memberships", json={"project":pid,"role":role["id"],"username":"loop-bot@example.com"}).status_code)
EOF

# token → append to .env
uv run --with httpx python -c "
from hub.taiga import auth_token
print('LOOPHUB_TAIGA_TOKEN=' + auth_token('http://localhost:9000','loop-bot','<loop-bot password>'))" >> .env
```

## 6. Start loop-hub and verify layer by layer

```bash
set -a; source .env; set +a
uv run --with fastapi --with uvicorn --with httpx python -m hub    # port 8400
```

Startup MUST log `resolved status ids` for all three projects — if it raises
instead, a column was renamed or a project id is wrong (that failure is loud on
purpose).

**Verification ladder** (each step proves one layer):

1. Unit tests: `uv run --with fastapi --with httpx --with uvicorn --with pytest python -m pytest -q` → 34 passed.
2. Signature: `curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8400/webhooks/taiga -H 'x-taiga-webhook-signature: bad' -d '{}'` → `403`.
3. Connector: create any card in the UI, then `uv run --with httpx --with fastapi --with uvicorn python scripts/m3_connector_check.py <story_id>` → 3 ✓ lines.
4. Webhook path: move any card between columns → hub log shows `status change: …`. If not, check Taiga Project → Settings → Integrations → webhook logs.
5. Spec agent: create a card **with the `repo` field set** (e.g. `bankapp`), drag To-Do → Spec Drafting → within ~2 min the spec appears in the card and it auto-moves to Spec Review.
6. Full loop: resolve/delete the spec's Open questions, drag Spec Review → Dev → loop runs (~3-6 min) → card lands in PR (or Spec Review with a failure report).

## 6b. Per-repo gate configuration (`loop.toml`)

A target repo may carry a `loop.toml` that loopengine + loop-hub honor:

```toml
[gate]
test_command    = "[ -d node_modules ] || npm ci --silent; npx ng test --watch=false"
gate_mode       = "synthesize"          # test-author agent writes the gate from the spec
author_dir      = "src/tests/acceptance/"
protected_paths = ["src/tests/"]        # extends the Actor's read-only set
```

Without a loop.toml the defaults apply: pytest as the runner, `provided` gate
(the repo's committed tests are the contract), `tests/` protected. hackDemo is
the reference example: its gate runs `ng test` (vitest/TestBed) and its
synthesized gate specs merge into `src/tests/` with each PR — the regression
suite grows automatically.

## 7. Demo-day preparation checklist

- [ ] Rehearse all three acts (runbook: `loopEngineer/docs/DEMO-RUNBOOK.md`, board-driven section) and record a backup video of each.
- [ ] Rehearse the failure drill: kill hub (`kill $(lsof -ti :8400)`), move a card, restart hub, watch `poller: re-enqueued story N` within 60 s.
- [ ] Reset the board: cards back to Backlog (keep comment history), `rm loopHub/loop-hub.sqlite3` for a clean queue.
- [ ] `docker compose up -d` + hub start after any reboot; Taiga data survives restarts (volumes).
- [ ] Timings to quote (measured 2026-07-09): spec draft 1m35s; 一次就過 3m13s; 自我修正 5m09s; 知所進退 escalates in 6m07s.

## Component map (what talks to what)

```
Browser ──▶ Taiga UI :9000 ──(signed webhook)──▶ loop-hub :8400 (host process)
                 ▲                                   ├─ Spec agent ── claude CLI
                 └────────(REST write-backs)─────────┤
                                                     └─ loopengine subprocess
                                                          └─ demo repos (local git)
```

Only outbound traffic is the claude CLI → model API. Board, repos, and run
records never leave the machine.
