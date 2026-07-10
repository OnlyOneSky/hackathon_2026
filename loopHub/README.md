# loop-hub

The control plane between the Taiga kanban board and the `loopengine` agentic
loop. One FastAPI process: verifies webhooks, enforces the board state machine
(8 moves, 5 guardrails), drafts specs with an LLM, and launches loop runs as
subprocesses. Design docs: `docs/superpowers/specs/2026-07-08-…` and `…-07-09-…`.

## Layout

```
hub/
  app.py         FastAPI app: webhook → decide() → enqueue/bounce; startup resolution
  transitions.py the state machine + guardrails (pure, unit-tested)
  events.py      webhook payload parsing/filtering
  security.py    HMAC-SHA1 raw-body signature verify
  queue.py       SQLite job queue (re-entry guard lives here)
  taiga.py       Taiga REST connector (version-locked PATCH write-backs)
  slack.py       human-gate notifications (spec ready / PR ready / escalated); no-op if unconfigured
  spec_agent.py  spec drafting: prompt assembly, claude CLI call, validator
  workers.py     spec_draft worker
  loop_runner.py loop_run worker: frozen spec → python -m loopengine run → write-back
config.toml      Taiga URL, column names (To-Do / Spec Drafting / Spec Review / Dev / PR / Done — shared by ALL projects), port
repos.toml       team-scoped repo registry (project id → team → repos)
.env             LOOPHUB_WEBHOOK_SECRET, LOOPHUB_TAIGA_TOKEN, TAIGA_ADMIN_PASSWORD (not committed)
scripts/
  m1_board_setup.py    idempotent Taiga board provisioning (projects, columns, webhook)
  m3_connector_check.py standalone connector smoke test against a scratch card
```

## Run

```bash
# Taiga (from taiga-docker/): docker compose up -d
cd loopHub
set -a; source .env; set +a
uv run --with fastapi --with uvicorn --with httpx python -m hub   # port 8400
```

Tests: `uv run --with fastapi --with httpx --with uvicorn --with pytest python -m pytest -q`

## Operational notes (learned in build-out)

- Taiga webhooks need `WEBHOOKS_ENABLED=True` **and**
  `WEBHOOKS_ALLOW_PRIVATE_ADDRESS=True` (NOT `WEBHOOKS_BLOCK_PRIVATE_ADDRESS` —
  that name doesn't exist) in the taiga-back/async env, because
  `host.docker.internal` is a private address. Failed deliveries show in
  Project → Settings → Integrations → webhook logs as
  `error-in-request: Private IP Address not allowed`.
- Events **by `loop-bot` are ignored** at the webhook: our own bounces/moves
  must never re-enter the state machine (else infinite bounce loops).
- The feedback-required guard likewise ignores loop-bot's comments.
- The approval snapshot comes from the signed payload's `data.description`;
  only the reconciliation poller falls back to GET.
- Board state is reset per demo by moving cards, not deleting: the history
  (comments) is part of the demo story.
- Column display names are GLOBAL config: renaming a column on one board means
  renaming it on all boards + config.toml, else startup resolution fails (by
  design). Current names: To-Do / Spec Drafting / Spec Review / Dev / PR / Done.
- Per-repo gate config lives in the target repo's loop.toml ([gate]
  test_command / gate_mode / author_dir / protected_paths) — see SETUP.md §6b.
  loop-hub passes gate_mode through to `loopengine run --gate`.
