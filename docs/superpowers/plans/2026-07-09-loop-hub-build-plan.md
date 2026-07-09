# loop-hub Build Plan — ordered milestones

**Date:** 2026-07-09
**Status:** M0–M9 complete (2026-07-09). Backup video (M9) still to record by hand.
**Designs this implements:**
- `docs/superpowers/specs/2026-07-08-kanban-spec-approval-flow-design.md` (board flow: 5 columns, 8 moves, guardrails)
- `docs/superpowers/specs/2026-07-09-agentic-loop-infrastructure-design.md` (loop-hub, Taiga, repo registry, Spec agent)

## Context for a fresh session

The agentic loop itself (`loopEngineer/`) **already exists, runs, and is out of
scope — do not modify it**. Everything below builds `loop-hub`: the FastAPI
service between the Taiga board and `python -m loopengine run`, per the two
design docs above. Ordering principle (from `loopEngineer/README.md`): test
every connector standalone before wiring anything into a flow; glue comes last.
Do not skip ahead — each milestone's "done when" gates the next.

Demo topology: Taiga in Docker, loop-hub as a host process (the Actor shells
out to the host's authenticated `codex`/`claude` CLIs). Multi-team: 3 Taiga
projects, team-scoped `repos.toml`, required `repo` custom attribute per card.

## Milestones — strict order

### [x] M0 · Prereqs (~30 min)
Inventory all team repos into `repos.toml` (3 teams × 3+ repos); create
`loop-bot` accounts (Taiga user; GitHub fine-grained PAT for the hackathon);
confirm `codex` / `claude` CLI auth works on the demo machine.

### [x] M1 · Board up (~1 h)
taiga-docker per the infra doc §3 setup (edit shipped `.env`;
`WEBHOOKS_ENABLED: "True"` and `WEBHOOKS_BLOCK_PRIVATE_ADDRESS: "False"` in the
taiga-back service env; `./launch-taiga.sh`; `./taiga-manage.sh createsuperuser`).
3 projects, 5 columns each (Backlog / Spec Drafting / Spec Review / Dev /
PR-Done + Done), required `repo` custom field, webhook per project →
`http://host.docker.internal:8400/webhooks/taiga` + secret.
**Done when:** moving any card produces a signed POST observable with `nc -l 8400`.

### [x] M2 · loop-hub skeleton (~half day)
FastAPI on host port 8400: raw-body HMAC-SHA1 verify via `hmac.compare_digest`;
event filter (`action=change`, `type=userstory`, status transitions we care
about); status-name→id resolution at startup (fail loudly on rename); SQLite
job queue; log-only workers.
**Done when:** card move → correct event logged; tampered signature → 403.

### [x] M3 · Taiga connector, standalone
`get_story` / `write_spec_and_move` (PATCH description+status+comment with
`version` lock) / bounce-with-comment. Exercise from a test script against a
scratch card BEFORE any agent is wired.
**Done when:** the script writes a description, moves a card, and comments.

### [x] M4 · Spec agent
Prompt file (infra doc §4), LLM call, output validator (frontmatter, `# Feature`,
≥1 `AC-`, cited §n exist in constitution). Test from CLI with a pasted story
first; then wire to the queue.
**Done when:** dragging a card to Spec Drafting yields a spec in the card and
the card auto-moves to Spec Review with the @reviewer comment.

### [x] M5 · Guardrails
Illegal-move bounce; `repo` validation at move ①; re-entry guard (one active
job/run per card); feedback-required on move ④; Open-questions block on
move ③; approval snapshot taken from the signed webhook payload
(`data.description`), GET only on the poller fallback path.
**Done when:** each guard demonstrably fires (skip a column; approve with open
questions; regenerate without a comment).

### [x] M6 · Dev trigger
Review→Dev webhook → frozen `runs/<run-id>/spec.md` → subprocess
`python -m loopengine run --spec … --repo … --agent codex`, repo resolved via
the team registry. The loop needs zero changes.
**Done when:** an approved card kicks a real run and the run record lands in
the runs dir.

### [x] M7 · Outcome write-backs
Converge → move ⑥ + PR artifact/link on the card; escalate → move ⑦ with the
failure report as a comment; merge (or demo equivalent) → Done.
**Done when:** all three endings are visible on the board with no manual API calls.

### [x] M8 · Full rehearsal + the honest number
Run the three demo acts end-to-end from card drag to board write-back:
一次就過 / 自我修正 / 知所進退. TIME a single-feature run — that measured
number goes into the proposal's 業務價值 section (currently qualitative only).

### [x] M9 · Demo hardening
Update `loopEngineer/docs/DEMO-RUNBOOK.md` for the board-driven flow; drill one
live failure (kill loop-hub mid-demo, show the reconciliation poller catch up);
record a backup video.

## Calendar guide
M0–M2 day one · M3–M5 day two · M6–M7 day three · M8–M9 last day.
Riskiest integration: M4's write-back (Taiga versioning + auto-move) — which is
why M3 proves the connector standalone first.
