# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

**Kanban-driven Agentic Loop — a banking-grade secure AI agent development paradigm.**
Entry for the **2026 Cathay AI Hackathon** (AI 工作效率應用挑戰 track).

The pitch: a PM drags a card across a five-column Kanban board and that single
gesture drives a controlled Actor↔Critic loop that writes code, runs tests, checks
it against a security "constitution," and produces a **reviewed, compliant PR** for
a human to merge. Under banking compliance guardrails, humans act only three times —
**submit the requirement, approve the spec, click merge** — everything else is AI.

The thesis: **the value is not in how smart the model is, but in the ring of
bank-auditable deterministic control code around it.** All safety gates live in our
own code, never inside the model.

## Core concept — "loop engineering"

Loop engineering is **not** a clever prompt or self-running magic. It is an ordinary
program (a `for` loop) you write, that calls the AI as one step inside it.

- An **agent** = one model call (or one `codex exec`) carrying a specific prompt.
- The **orchestrator (our code)** decides who to call, in what order, when to retry,
  when to stop.
- The model provides intelligence; the loop provides control, safety caps, and wiring
  to external systems.

## The five-column Kanban flow

`Backlog → Spec Drafting → Spec Review → Dev → PR/Done`, left to right, with 8 legal
moves. **Moving a card triggers; sending a card back is feedback.**

- Backlog → Spec Drafting: AI writes a **testable spec draft** back onto the card.
- Spec Review: engineer confirms/edits the spec on the card. **Dragging into Dev is
  approval** — a snapshot is frozen at that moment for audit.
- Dev: the Agentic Loop runs (write → enforce → test → QA → security).
- Three spec-review exits: **approve** (snapshot-freeze), **regenerate** (must attach
  feedback), **return to PM** (requirement was wrong).
- Loop hitting the cap (⑦) and a substantively-rejected PR (⑧) both route back to the
  spec column — "the spec is always the reason the code exists."

## Repository layout

| Path | Role |
|------|------|
| `loopEngineer/` | The runnable prototype — the controlled spec-to-PR agentic loop |
| `docs/proposal/Entry-proposal-v2.html` | The one-page proposal (source of the vision above) |
| `docs/diagrams/` | The five-column Kanban architecture diagram (SVG/PNG) |
| `docs/superpowers/specs/` | Design specs for the spec-approval flow |
| `Entry proposal v2.pdf` | Rendered proposal (same content as the HTML) |

### Inside `loopEngineer/` — the 5 + memory building blocks (one module each)

| Block | Module | Job |
|-------|--------|-----|
| Automations | `loopengine/trigger.py` | CLI entrypoint; ingest `spec.md`; own the caps |
| Worktrees | `loopengine/isolation.py` | isolated git worktree + protected-path enforcement |
| Skills | `skills/` | constitution + prompts, **read-only to the actor** |
| Connectors | `loopengine/connectors.py` | pytest gate, git helpers, PR artifact |
| Sub-agents | `loopengine/agents.py` | Codex actor (write) + QA/security critics (read-only) |
| Memory | `loopengine/memory.py` | durable per-run state; the loop's spine |

`loopengine/orchestrator.py` is thin glue. Other modules: `config.py` (caps),
`gate.py`, `reporter.py`, `slack.py`, `demo.py`. Demo scenarios live in
`loopEngineer/demo/` (`bankapp`, `website`, `impossible`, `greenfield-transfer`).

## Commands

All commands run from `loopEngineer/`. Setup once:
`python3.13 -m venv .venv && .venv/bin/python -m pip install pytest`

```bash
# Offline test suite (mock agent, no API keys)
.venv/bin/python -m pytest -q

# Run for real on this dev machine (Claude Code as the agent)
.venv/bin/python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp \
  --agent claude          # default

# Run for the demo on the work machine (Codex CLI as the agent)
.venv/bin/python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp \
  --agent codex
```

Key flags: `--max-iterations N` (clamped to hard ceiling of 6),
`--constitution PATH`, `--gate synthesize` (phase 0: an independent agent writes the
acceptance gate from the spec before the loop). Slack status stream is opt-in via
`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`.

Before a live Codex run, run `.venv/bin/python scripts/codex_smoke.py` once to confirm
the flags. Actor runs `codex exec --sandbox workspace-write`; critics run
`codex exec --sandbox read-only`.

## Safety properties — treat these as hard invariants

These are the whole point of the project. Do not weaken them.

- **Bounded:** `MAX_ITERATIONS = 6`, `MAX_WALL_SECONDS = 1200`, `GATE_MAX_ATTEMPTS = 3`
  (see `loopengine/config.py`). Caps are owned by our code, not the model.
- **Read-only verification:** tests and the constitution are read-only to the actor.
  Tampering is **detected via `git diff` and reverted** (anti-reward-hacking).
- **Deterministic-first:** pytest decides pass/fail **before** any LLM critic is spent —
  the model never self-certifies.
- **No auto-merge:** convergence produces a **PR artifact for a human gate**, never an
  automatic merge.
- **Connector guardrails (outside the loop):** approval snapshots, illegal-move
  rejection, role-based move permissions, mandatory feedback on send-back, one active
  run per card.

## Working conventions

- **Do not modify** `tests/` or `constitution.md` from an actor/implementation role —
  they are the guardrail, and the loop actively detects and reverts such changes.
- The orchestrator is glue; safety logic belongs in the deterministic connector/gate
  code, never in prompts.
- Python 3.11+ (3.13 on this dev machine); `pytest` is the only test dependency.
- **Language:** technical docs/code in English; the proposal and product-facing docs are
  in **Traditional Chinese (繁體中文)**. Never use Simplified Chinese anywhere.
