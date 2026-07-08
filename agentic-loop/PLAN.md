# Realizing the Kanban-Driven Agentic Loop — Implementation Plan

This plan turns the proposal in `Cathay_AI_Hackathon_v2.pdf` into something
buildable. It records the decisions we settled on, what is already working in
this folder, what still has to be wired to live services, and the handful of
things in the PDF that cannot be built literally (with the substitute in each
case).

The scope agreed: **a working vertical slice plus this plan.** The slice runs
the full controlled loop locally — real `pytest` gates, real `git diff`
enforcement, real iteration/time caps, both human gates — with the Codex calls
and the external services (Taiga, GitHub) faked so it runs with no network. The
plan below covers swapping the fakes for the real services.

---

## 1. What the proposal asks for

A card flows left to right across a Kanban board: Backlog → Spec → Dev →
PR/Done. There are **two automated triggers**, with a human decision between
them:

- **Backlog → Spec** triggers spec generation: an AI agent reads the
  requirement and writes a testable spec, then Slack notifies the assigned
  developer to review it.
- **Human gate #1 (in the Spec column, OUTSIDE the loop):** the developer
  reviews the spec and either approves it — *by moving the card to Dev* — edits
  it, or rejects it (card returns to Backlog). The card move **is** the approval.
- **Spec → Dev** triggers the controlled Actor↔Critic loop: an Actor (Codex)
  writes code; deterministic gates run the tests, enforce a read-only
  "constitution," and cap the iterations at 6. On success it opens a compliant
  PR; after 6 failures the card goes back to Backlog (tagged, with a Slack
  notice).
- **Human gate #2 (PR/Done):** a developer reviews and merges the PR.

The key point I had wrong initially: spec generation and the spec review both
happen *before* and *outside* the Agentic Loop. The loop itself is only
Actor → tests → QA → Security → retry.

The value for a bank is not the model — it is the *outer loop*: the dull control
and safety code around the model (caps, read-only enforcement, the test gate,
the human gates). That code is what makes "let an AI write banking code" safe.

## 2. What already exists vs. the gap

The folder you were given (`orchestrator.py`, the four prompts, `constitution.md`,
the README, the end-to-end example) is a faithful *reference* of the loop logic —
but it is explicitly "not turnkey": placeholder paths, no Kanban trigger, console
stubs for the human gates, and a couple of internal inconsistencies (see §6).

The gap to "realizing" it is the integration layer: the card-move trigger, the
connectors, a real demo target to operate on, and the model wiring. This slice
fills that gap in runnable form.

## 3. Decision: Codex-only

You asked whether this can be done with Codex CLI alone. **Yes**, and it is the
cleaner design. All four roles run as `codex exec`, separated only by sandbox:

| Role     | Invocation                              | Why safe |
| -------- | --------------------------------------- | -------- |
| Actor    | `codex exec --sandbox workspace-write`  | may edit repo files, nothing broader |
| Spec     | `codex exec --sandbox read-only`        | physically cannot write |
| QA       | `codex exec --sandbox read-only`        | physically cannot write |
| Security | `codex exec --sandbox read-only`        | physically cannot write |

The safety argument never depended on "use a second vendor." It rests on (a) the
critics being sandboxed read-only, and (b) the **test gate being our own
deterministic code**, not the model's self-report. Both hold here, with a single
auth. The one honest tradeoff — Actor and critics share a model family, so a
blind spot could correlate — is contained by the deterministic `pytest` +
`git diff` gates, which don't care which model produced the code.

## 4. Architecture — what runs where

```
 Taiga board                  our service (one host)                    GitHub
 ───────────                   ─────────────────────                    ──────
 ① card Backlog→Spec ─webhook─▶ taiga_webhook.dispatch()
                                 └▶ generate_spec_stage()  (codex read-only)
                                      writes spec.json ─────────────────┐
                                      Slack: "review the spec" ◀────── Slack
                                                                        │
 ② developer reviews spec.json  (HUMAN GATE #1 — done by the human in Taiga)
    approve = move card Spec→Dev   ·   edit spec   ·   reject = move →Backlog
                                                                        │
 ③ card Spec→Dev ────webhook──▶ taiga_webhook.dispatch()                │
                                 └▶ agentic_loop()  reads spec.json ◀────┘
                                      for attempt in 1..6:
                                        Actor      (codex workspace-write)
                                        git diff   protected-file enforce ← OUR code
                                        pytest     deterministic gate      ← OUR code
                                        QA         (codex read-only)
                                        Security   (codex read-only)
                                      ┌── all pass ──▶ commit ──push──▶ branch
                                      │                github_pr ──────▶ PR (not merged)
                                      │                Slack: "awaiting review"
                                      └── 6x fail ──▶ taiga_board.move_card →Backlog
                                                       Slack: "returned, <reason>"
                                                                        │
                                                          HUMAN GATE #2 │ review + merge
                                                                        ▼  → CI deploys
```

Board columns: **Backlog** (PM files the requirement) → **Spec** (AI writes the
spec; human gate #1 reviews it — *the move to Dev is the approval*) → **Dev**
(the Actor↔Critic loop; entering this column is the second trigger) → **PR/Done**
(PR opened; human gate #2 merges).

### Files in this slice

| File | Role |
| --- | --- |
| `orchestrator.py` | `generate_spec_stage()` + `agentic_loop()`; caps, gates, enforcement; `mode="mock"`/`"codex"` |
| `mock_codex.py` | deterministic stand-ins for the 4 roles so it runs offline |
| `connectors/taiga_webhook.py` | inbound: routes →Spec to spec gen, →Dev to the loop (HMAC-verified) |
| `connectors/taiga_board.py` | outbound: moves a card (e.g. back to Backlog on 6x fail) |
| `connectors/github_pr.py` | opens a PR, never merges (dry-run in mock mode) |
| `connectors/slack_notify.py` | the spec-ready / PR-ready / returned-to-Backlog notices |
| `prompts/*.txt` | the 4 role prompts, adapted for Codex-only |
| `constitution.md` | versioned, read-only-to-Actor rule set |
| `demo_bankapp/` | a tiny bank module + failing acceptance tests = the target |
| `run_demo.py` | throwaway git repo; runs both stages with the human decision between |

## 5. The gates (what makes it safe)

Deterministic, our code, the model has no say:

- **Iteration cap** (`MAX_ITERATIONS = 6`) and **wall-clock cap**
  (`MAX_WALL_SECONDS = 1200`) — the loop cannot run away. Verified: the `never`
  scenario escalates at attempt 6.
- **Read-only-tests enforcement** — after the Actor runs, `git diff` checks it
  did not touch `tests/` or `constitution.md`; if it did, those files are
  reverted and the attempt is rejected. Verified: the `tamper` scenario is caught
  and reverted. This is the concrete anti-reward-hacking control.
- **Test gate** — *we* run `pytest`; the Actor never certifies its own work.
- **PR, not merge** — the loop opens a PR carrying the QA + Security reports; a
  human merges.
- **Failure returns to a human, not a void** — after 6 failed iterations the
  card is moved back to Backlog (tagged) with a Slack notice, rather than the
  loop silently spinning or dropping the work.

Two human gates, both expressed as Kanban actions rather than code:
**#1** is the spec review — the developer approves by *moving the card Spec → Dev*
(or edits, or rejects → Backlog). This is the one thing no automated gate can
check (spec-vs-business-intent), and it sits *outside* the loop, before any code
is written. **#2** is the PR Review & Merge. In the slice, gate #1 is a simulated
developer decision (`--decision approve|edit|reject`) and gate #2 is a dry-run
PR; §7 covers wiring them to live Taiga/Slack/GitHub.

## 6. Issues found in the PDF / reference, and how this slice resolves them

1. **"Jenkins" listed as a Kanban tool** (PDF p.1). Jenkins is CI; it has no
   draggable card board, so it cannot be the *trigger*. Resolution: the trigger
   comes from Taiga (a real Kanban tool with webhooks); Jenkins/GitHub Actions
   belong on the *CI* side after the PR.
2. **"自訂 GPT" (Custom GPTs) as loop agents** — not buildable as described.
   Custom GPTs are a ChatGPT-UI feature with no automation API; you cannot call
   one programmatically inside a loop. Resolution: the roles are `codex exec`
   calls (or any model API) with the role prompt as input. Same idea, real
   mechanism.
3. **Actor contract was self-contradictory** — `actor.txt` told the model to
   emit JSON files, but the orchestrator/README had Codex edit files on disk and
   ignored its text. Resolution: rewrote `actor.txt` to "edit files on disk, do
   not emit JSON, do not commit."
4. **Prompt templates would crash** — the reference prompts contained literal
   `{` / `}` (JSON examples) but are fed through Python `str.format()`, which
   would raise `KeyError`. Resolution: escaped them as `{{` / `}}`; verified all
   four render.
5. **Placeholder wiring** — `REPO_DIR = "/path/to/local/clone"`, console-`input`
   human gates, sketched helpers. Resolution: `run_demo.py` builds a real
   throwaway git repo; connectors have real + dry-run paths; the human gates are
   modelled as the Kanban moves they actually are (see #6).
6. **The flow had one trigger, not two** — the reference `run_loop()` generated
   the spec, ran an in-loop spec review, and ran the Actor↔Critic loop all in one
   call triggered by "move to Dev." The board actually has two triggers with the
   human decision between them. Resolution: split into `generate_spec_stage()`
   (fires on Backlog→Spec) and `agentic_loop()` (fires on Spec→Dev); spec review
   is no longer code inside the loop — it is the developer moving the card, so
   the loop only ever sees an already-approved spec.

## 7. From slice to production — wiring the real services

1. **Codex**: install the Codex CLI on the runner and authenticate (login or
   `OPENAI_API_KEY`). Smoke-test once: `codex exec --json "say hi"` and confirm
   the final JSON event shape, then run the stages with `mode="codex"`.
2. **GitHub**: set `REPO_SLUG` and a repo-scoped `GITHUB_TOKEN`; point `REPO_DIR`
   at a clean local clone. `github_pr.open_pull_request` then pushes the branch
   and opens the PR. Branch protection should require the PR (enforces gate #2).
3. **Taiga**: run `connectors/taiga_webhook.py` on a reachable host; add a
   project webhook → `http://<host>:8099/taiga` with a secret
   (`TAIGA_WEBHOOK_SECRET`) so the HMAC-SHA1 signature is verified. Name the
   columns `Spec` and `Dev` (or set `SPEC_COLUMN` / `DEV_COLUMN`). For the
   outbound move-back-to-Backlog, set `TAIGA_URL`, `TAIGA_AUTH_TOKEN`, and the
   per-column status-id env vars (`taiga_board.py`).
4. **Slack**: set `SLACK_WEBHOOK_URL` for the spec-ready / PR-ready /
   returned-to-Backlog notices.
5. **Human gates need no extra code** — gate #1 is the developer moving the card
   Spec→Dev in Taiga (which is already trigger 2); gate #2 is the PR Review &
   Merge. The only thing to build is making the spec easy to review (e.g. post
   `spec.json` into the Slack message or attach it to the card).
6. **CI**: on the demo we run `pytest` locally for speed. In production, dispatch
   the suite via GitHub Actions and read the result back, so tests run in a clean
   environment.
7. **Constitution**: keep it in the repo under version control. Adding a clause
   immediately extends the safety net to all later changes, and other teams can
   adopt the same file — this is the "spreadable" part of the proposal.

Sequencing matches the reference README's advice: verify each prompt alone, then
each connector alone, then connect the loop last (the loop is just glue).

## 8. Risks and honest limits

- **Live loop needs a real environment** — Codex auth + network to GitHub +
  Taiga. It cannot run in a no-network sandbox; the mock mode exists precisely so
  the *control logic* is demonstrable without them.
- **Codex event schema drifts** — `_last_json()` is permissive, but confirm the
  real `--json` final-message shape before trusting the critics' verdicts.
- **Critics are LLM judgement** — the Security Critic can miss a violation. It is
  a second layer behind the deterministic gates, not a substitute; keep
  high-value rules expressible as tests where possible.
- **Local pytest in mock mode trusts the runner** — fine for a demo; use CI in
  production so the Actor cannot influence the test environment.
- **Effort is still qualitative** — the honest next step (per the reference) is
  to time one real single-feature run and report it, to firm up the
  business-value claim.

## 9. Hackathon demo script (≈3 min)

1. Show the failing target: `pytest demo_bankapp/tests` → 2 red (the feature is
   missing). Show `constitution.md`.
2. `python3 run_demo.py normal` — narrate the two triggers: card Backlog→Spec
   writes the spec + Slack notice (trigger 1) → developer approves at human gate
   #1 (card Spec→Dev, trigger 2) → loop iteration 1 fails the boundary test →
   iteration 2 fixes it → QA + Security pass → PR opened, Slack "awaiting review."
3. `python3 run_demo.py normal --decision reject` — developer rejects the spec;
   card goes back to Backlog, **no code is ever written.** "Wrong target gets
   stopped before the machine starts — the cheapest place to catch it."
4. `python3 run_demo.py tamper` — the Actor tries to weaken a test; `git diff`
   catches and reverts it; the loop recovers. "The anti-reward-hacking control."
5. `python3 run_demo.py never` — the loop fails 6× and returns the card to
   Backlog with a tag + Slack notice. "It cannot run away; it hands back to a
   human with a reason."
6. Close on the guarantees: two triggers driven by natural Kanban moves, capped,
   verifiable, and human-gated at both ends.
