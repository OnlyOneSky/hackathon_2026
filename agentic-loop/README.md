# Kanban-Driven Agentic Loop — runnable slice

A controlled, Kanban-driven Actor↔Critic loop for safe, AI-written banking code.
The board has **two automated triggers** with a human decision between them:

```
Backlog ──▶ Spec ──────────▶ Dev ─────────────▶ PR / Done
        (1)      (human #1)      (Agentic Loop)
   AI writes spec   developer    Actor → tests →   PR opened,
   + Slack notice   approves by  QA → Security →    human #2
                    moving →Dev  retry (≤6)         reviews & merges
```

See `PLAN.md` for the full design and rollout plan.

This slice runs the **entire flow locally with no Codex and no network**: the
`pytest` gate, the `git diff` read-only-tests enforcement, the iteration cap, and
the Slack/Taiga side effects are all real (Slack/Taiga print in mock mode) — only
the model calls and the external services are faked.

## Run the demo

```bash
cd agentic-loop
pip install pytest          # the only dependency for mock mode

python3 run_demo.py normal                    # approve -> loop converges -> PR opened
python3 run_demo.py normal --decision reject  # spec rejected -> card back to Backlog, no code
python3 run_demo.py tamper                    # actor edits a test -> caught & reverted
python3 run_demo.py never                     # loop fails 6x -> card back to Backlog
```

What each run proves:

- **normal** — both triggers + the test→fix→retest loop. Trigger 1 writes the
  spec; the developer approves (human gate #1); trigger 2 starts the loop;
  iteration 1 ships a boundary bug (`>=`), the test gate fails, iteration 2 fixes
  it (`>`), QA + Security pass, a PR is opened (never auto-merged).
- **reject** — human gate #1 is real and *outside* the loop. The developer
  rejects the spec, the card returns to Backlog, and no code is ever written.
- **tamper** — anti-reward-hacking. The Actor tries to weaken a protected test;
  `git diff` detects it, reverts it, and rejects the attempt.
- **never** — runaway protection. The Actor never fixes the bug; the loop stops
  at `MAX_ITERATIONS` and returns the card to Backlog (tagged) with a Slack notice.

## Files

| File | Role |
| --- | --- |
| `orchestrator.py` | `generate_spec_stage()` + `agentic_loop()`; caps, gates, enforcement; `mode="mock"`/`"codex"` |
| `mock_codex.py` | deterministic stand-ins for the 4 Codex roles (offline) |
| `prompts/` | the 4 role prompts (Spec / Actor / QA / Security), Codex-only |
| `constitution.md` | versioned rule set; read-only to the Actor |
| `connectors/taiga_webhook.py` | inbound: →Spec triggers spec gen, →Dev triggers the loop (HMAC-verified) |
| `connectors/taiga_board.py` | outbound: move a card (e.g. back to Backlog on 6x fail) |
| `connectors/github_pr.py` | opens a PR, never merges |
| `connectors/slack_notify.py` | spec-ready / PR-ready / returned-to-Backlog notices |
| `demo_bankapp/` | tiny bank module + failing acceptance tests = the target |
| `run_demo.py` | throwaway git repo; runs both stages with the human decision between |
| `sample_taiga_webhook.json` | example payload: card moved Backlog→Spec (trigger 1) |
| `sample_taiga_to_dev.json` | example payload: card moved Spec→Dev (trigger 2) |

## Switching to real services

Set `mode="codex"` and provide the environment described in `PLAN.md` §7:
Codex CLI authenticated; `REPO_SLUG` + `GITHUB_TOKEN` + a clean `REPO_DIR` clone;
`SLACK_WEBHOOK_URL`; a Taiga webhook with `TAIGA_WEBHOOK_SECRET`. Then:

```bash
REPO_DIR=/path/to/clone LOOP_MODE=codex \
    SLACK_WEBHOOK_URL=... TAIGA_WEBHOOK_SECRET=... \
    python3 -m connectors.taiga_webhook      # listens on :8099/taiga
```

The listener routes `→Spec` to spec generation and `→Dev` to the Agentic Loop.
The approval in between is a human moving the card in Taiga — no code path.
