"""orchestrator.py — the controlled, Kanban-driven loop. Codex-only.

The board has two AUTOMATED triggers, not one (this matches the proposal):

  Backlog -> Spec   triggers  generate_spec_stage()   (AI writes the spec, then
                              Slack notifies the developer to review it)

  --- HUMAN GATE #1 happens HERE, OUTSIDE this code ---
  A developer reviews the spec in Taiga and either approves it (by MOVING the
  card Spec -> Dev), edits it, or rejects it (moves it back to Backlog). The
  card move IS the approval; the system does not auto-advance it.

  Spec -> Dev       triggers  agentic_loop()          (the Actor<->Critic loop
                              ONLY: Actor -> tests -> QA -> Security -> retry,
                              capped at 6; output is a PR, or the card goes back
                              to Backlog)

  --- HUMAN GATE #2 ---  Review & Merge the PR (PR/Done column).

The model supplies intelligence; THIS code supplies control: the caps, the
read-only-tests enforcement, the deterministic test gate. None of that is the
model's to decide.

ROLES (all `codex exec`, differing only by sandbox):
  Actor    -> --sandbox workspace-write   (edits files on disk)
  Spec/QA/Security -> --sandbox read-only  (judgement, physically cannot write)

MODES: "codex" = real codex calls; "mock" = deterministic stand-ins so the whole
thing runs offline. Even in mock mode the pytest gate, git-diff enforcement, and
caps are REAL — only the model calls and external services are faked.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Callable

import mock_codex
from connectors import github_pr, slack_notify, taiga_board

# ----------------------------------------------------------------------------
# CONFIG / safety limits — deterministic; the agent has no say over these.
# ----------------------------------------------------------------------------
MAX_ITERATIONS = 6
MAX_WALL_SECONDS = 1200
PROTECTED = ("demo_bankapp/tests/", "constitution.md")   # Actor must not touch
PROMPTS = Path(__file__).parent / "prompts"
SPEC_FILE = "spec.json"   # the approved spec persists here between the 2 stages


class LoopResult(dict):
    """Just a dict; named for readability in logs."""


# ============================================================================
# AGENT DISPATCH — one entry point, two backends (real Codex / mock).
# ============================================================================
def _run_codex(prompt: str, sandbox: str, repo_dir: Path) -> str:
    proc = subprocess.run(
        ["codex", "exec", "--sandbox", sandbox, "--json",
         "--skip-git-repo-check", prompt],
        cwd=repo_dir, capture_output=True, text=True, timeout=600)
    return proc.stdout


def _last_json(stream: str) -> dict:
    for line in reversed(stream.strip().splitlines()):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return {}


class Agents:
    def __init__(self, repo_dir: Path, mode: str = "mock", scenario: str = "normal"):
        self.repo_dir = repo_dir
        self.mode = mode
        self.scenario = scenario
        self._attempt = 0

    def spec(self, request: str, constitution: str) -> dict:
        if self.mode == "mock":
            return mock_codex.spec(request)
        prompt = (PROMPTS / "spec.txt").read_text().format(
            request=request, constitution=constitution)
        return _last_json(_run_codex(prompt, "read-only", self.repo_dir))

    def actor(self, spec: dict, last_error: str) -> None:
        if self.mode == "mock":
            mock_codex.actor(self.repo_dir, self.scenario, self._attempt, last_error)
            self._attempt += 1
            return
        prompt = (PROMPTS / "actor.txt").read_text().format(
            spec=json.dumps(spec, ensure_ascii=False),
            last_error=last_error or "(first attempt)")
        _run_codex(prompt, "workspace-write", self.repo_dir)

    def qa(self, spec: dict, code_diff: str, tests: dict) -> dict:
        if self.mode == "mock":
            return mock_codex.qa(self.repo_dir)
        prompt = (PROMPTS / "qa_critic.txt").read_text().format(
            spec=json.dumps(spec, ensure_ascii=False),
            code=code_diff, test_results=json.dumps(tests))
        return _last_json(_run_codex(prompt, "read-only", self.repo_dir))

    def security(self, spec: dict, constitution: str, code_diff: str) -> dict:
        if self.mode == "mock":
            return mock_codex.security(self.repo_dir)
        prompt = (PROMPTS / "security_critic.txt").read_text().format(
            applicable_constitution=json.dumps(spec.get("applicable_constitution", [])),
            constitution=constitution, code=code_diff)
        return _last_json(_run_codex(prompt, "read-only", self.repo_dir))


# ============================================================================
# DETERMINISTIC GATES — OUR code. The model never self-certifies these.
# ============================================================================
def _git(repo_dir: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo_dir), *args],
                          capture_output=True, text=True).stdout


def assert_no_protected_changes(repo_dir: Path) -> tuple[bool, str]:
    """Read-only-tests rule, enforced AFTER the Actor runs: if it edited tests/
    or the constitution, revert those files and reject the attempt. This is the
    concrete anti-reward-hacking control."""
    changed = _git(repo_dir, "diff", "--name-only").split()
    violations = [f for f in changed if f.startswith(PROTECTED) or f in PROTECTED]
    if violations:
        _git(repo_dir, "checkout", "--", *violations)
        return False, f"Actor modified protected files (reverted): {violations}"
    return True, ""


def run_tests(repo_dir: Path) -> dict:
    proc = subprocess.run(["python3", "-m", "pytest", "-q", "demo_bankapp/tests"],
                          cwd=repo_dir, capture_output=True, text=True)
    return {"passed": proc.returncode == 0, "errors": proc.stdout + proc.stderr}


def diff_against_main(repo_dir: Path) -> str:
    return _git(repo_dir, "diff", "main", "--", ".")


# ============================================================================
# STAGE 1 — triggered by Backlog -> Spec. Generate the spec, notify the human.
# (HUMAN GATE #1 is NOT here: it is the developer moving the card Spec -> Dev.)
# ============================================================================
def generate_spec_stage(
    request: str,
    repo_dir: Path,
    *,
    mode: str = "mock",
    card_ref: int | str = "?",
    log: Callable[[str], None] = print,
) -> dict:
    repo_dir = Path(repo_dir)
    constitution = (repo_dir / "constitution.md").read_text()
    log("STEP Spec: AI reads the requirement and writes a testable spec")
    spec = Agents(repo_dir, mode=mode).spec(request, constitution)

    # Persist the spec so the developer can review it and the Dev stage can read
    # the APPROVED (possibly human-edited) version.
    (repo_dir / SPEC_FILE).write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    log(f"     spec written to {SPEC_FILE}: {spec.get('summary', '')}")

    slack_notify.notify(
        f"Spec ready for card #{card_ref}. Review in Taiga: "
        f"approve (move Spec→Dev) / edit / reject (move →Backlog).", mode=mode)
    return spec


# ============================================================================
# STAGE 2 — triggered by Spec -> Dev. The Actor<->Critic loop ONLY.
# The spec is already approved (the card move was the approval).
# ============================================================================
def agentic_loop(
    repo_dir: Path,
    *,
    mode: str = "mock",
    scenario: str = "normal",
    card_ref: int | str = "?",
    branch: str = "feature/transfer-limit",
    pr_opener: Callable[..., str] = github_pr.open_pull_request,
    log: Callable[[str], None] = print,
) -> dict:
    start = time.time()
    repo_dir = Path(repo_dir)
    constitution = (repo_dir / "constitution.md").read_text()
    spec = json.loads((repo_dir / SPEC_FILE).read_text())  # the approved spec
    agents = Agents(repo_dir, mode=mode, scenario=scenario)

    _git(repo_dir, "checkout", "-B", branch, "main")
    last_error = ""

    for attempt in range(1, MAX_ITERATIONS + 1):
        if time.time() - start > MAX_WALL_SECONDS:
            return _return_to_backlog(card_ref, "wall-clock cap", attempt - 1, mode, log)
        log(f"\n--- Agentic Loop iteration {attempt}/{MAX_ITERATIONS} ---")

        log("STEP Actor: implementing the spec (codex workspace-write)")
        agents.actor(spec, last_error)

        ok, why = assert_no_protected_changes(repo_dir)
        if not ok:
            log(f"GATE Anti-tamper: {why}")
            last_error = why
            continue

        log("GATE Tests: running pytest ourselves")
        tests = run_tests(repo_dir)
        if not tests["passed"]:
            log("     tests FAILED -> feeding failure back to the Actor")
            last_error = f"Tests failed:\n{_tail(tests['errors'])}"
            continue
        log("     tests PASSED")

        log("GATE QA Critic: under-tested / unmet criteria (codex read-only)")
        qa = agents.qa(spec, diff_against_main(repo_dir), tests)
        if qa.get("verdict") == "fail":
            last_error = f"QA gaps:\n{json.dumps(qa.get('gaps'))}"
            continue

        log("GATE Security Critic: clause-by-clause vs constitution (read-only)")
        sec = agents.security(spec, constitution, diff_against_main(repo_dir))
        if sec.get("verdict") == "fail":
            last_error = f"Constitution violations:\n{json.dumps(sec.get('findings'))}"
            continue

        # All gates passed -> commit, open PR for HUMAN GATE #2.
        log("\nAll gates passed -> opening PR (NOT merging; human reviews & merges)")
        _git(repo_dir, "add", "-A")
        _git(repo_dir, "commit", "-m", "agent: implement daily transfer-limit validation")
        url = pr_opener(branch=branch, qa=qa, security=sec, mode=mode, repo_dir=repo_dir)
        slack_notify.notify(
            f"Card #{card_ref}: compliant PR opened, awaiting Review & Merge — {url}",
            mode=mode)
        return LoopResult(status="pr_opened", attempts=attempt, pr=url, qa=qa, security=sec)

    return _return_to_backlog(card_ref, last_error, MAX_ITERATIONS, mode, log)


def _return_to_backlog(card_ref, reason: str, attempts: int, mode: str,
                       log: Callable[[str], None]) -> dict:
    """Failure path from the diagram: >6 failures -> card back to Backlog,
    tagged, with a Slack notice."""
    tag = "需求不清 / unclear-requirement-or-real-failure"
    log(f"\nAgentic Loop did not converge ({attempts} attempts) -> returning card to Backlog")
    taiga_board.move_card(card_ref, "Backlog", tag=tag, mode=mode)
    slack_notify.notify(
        f"Card #{card_ref}: Agentic Loop failed {attempts}x -> returned to Backlog "
        f"({tag}). Reason: {_tail(reason, 300)}", mode=mode)
    return LoopResult(status="returned_to_backlog", attempts=attempts, reason=reason)


def _tail(s: str, n: int = 1200) -> str:
    return s[-n:]
