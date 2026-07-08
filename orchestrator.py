"""
orchestrator.py — hybrid loop with Codex CLI as the Actor.

KEY IDEA vs. the raw-API version (kept as orchestrator_rawapi.py):
The Actor is no longer "a model that returns code that we write to disk."
It is `codex exec` — an agent that reads the repo and EDITS FILES ON DISK itself.
So the file-writing connector disappears from the Actor step.

What does NOT change, and is the whole safety argument of the entry:
the GATES stay as OUR deterministic code, OUTSIDE Codex —
  - run_tests()        : we trigger the tests ourselves; Codex never self-certifies
  - security_check()   : read-only Critic vs the constitution
  - the iteration cap  : we own the for-loop
  - read-only-tests rule : we ENFORCE it with `git diff` after Codex runs
  - human merge gate   : we open a PR; a person approves the merge

Read run_loop() at the bottom first.
"""

import os, json, time, subprocess, requests
from pathlib import Path

# ----------------------------------------------------------------------------
# CONFIG / safety limits — deterministic, the agent has no say over these.
# ----------------------------------------------------------------------------
MAX_ITERATIONS   = 6
MAX_WALL_SECONDS = 1200
REPO_DIR  = Path("/path/to/local/clone/bankapp")   # Codex edits files HERE
REPO_SLUG = "yourorg/bankapp"
BRANCH    = "feature/transfer-limit"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
# Codex auth: set OPENAI_API_KEY (recommended for automation) in the environment.

PROMPTS      = Path(__file__).parent / "prompts"
CONSTITUTION = (REPO_DIR / "constitution.md").read_text()
# Paths the Actor is FORBIDDEN to touch. Enforced after it runs.
PROTECTED = ("tests/", "constitution.md")


# ============================================================================
# THE ACTOR — now a Codex CLI subprocess, not a raw API call.
# ============================================================================
def codex_actor(spec: dict, last_error: str) -> dict:
    """Run Codex headlessly to implement the spec by editing files on disk.

    Flags that matter:
      exec                      -> non-interactive; do the task and exit
      --sandbox workspace-write -> may edit files in the repo, nothing broader
      --json                    -> stream structured JSONL events we can parse
      --skip-git-repo-check     -> we manage the branch ourselves
    Progress streams to stderr; the final agent message is the last JSON event.
    """
    prompt = (PROMPTS / "actor.txt").read_text().format(
        spec=json.dumps(spec, ensure_ascii=False),
        code_context="(Codex reads the repo itself)",
        last_error=last_error or "(first attempt)",
    )
    proc = subprocess.run(
        ["codex", "exec",
         "--sandbox", "workspace-write",
         "--json",
         "--skip-git-repo-check",
         prompt],
        cwd=REPO_DIR, capture_output=True, text=True, timeout=600,
    )
    # We don't need Codex's text output to "trust" it — the source of truth is
    # what changed on disk, verified next. JSONL is for logging/debugging only.
    return {"final": _last_json_line(proc.stdout), "raw": proc.stdout}


# ============================================================================
# ENFORCEMENT — read-only-tests rule, checked AFTER Codex runs.
# With the raw API we controlled writes directly. With a CLI agent we let it
# write, then VERIFY it didn't touch anything forbidden. Same guarantee.
# ============================================================================
def assert_no_protected_changes() -> tuple[bool, str]:
    changed = subprocess.run(
        ["git", "-C", str(REPO_DIR), "diff", "--name-only"],
        capture_output=True, text=True).stdout.split()
    violations = [f for f in changed if f.startswith(PROTECTED) or f in PROTECTED]
    if violations:
        # Codex tried to modify tests or the constitution -> roll back + reject.
        subprocess.run(["git", "-C", str(REPO_DIR), "checkout", "--", *violations])
        return False, f"Actor modified protected files: {violations}"
    return True, ""


# ============================================================================
# CONNECTORS — plain functions that reach real systems.
# The SAFETY-CRITICAL ones are ours, never exposed to the agent to call.
# ============================================================================
GH = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}

def commit_and_push():
    subprocess.run(["git", "-C", str(REPO_DIR), "add", "-A"])
    subprocess.run(["git", "-C", str(REPO_DIR), "commit", "-m", "agent: implement feature"])
    subprocess.run(["git", "-C", str(REPO_DIR), "push", "origin", BRANCH])

def run_tests() -> dict:
    """DETERMINISTIC GATE. We run tests ourselves — Codex never certifies itself.
    Run locally for speed (shown), or dispatch CI via the Actions API."""
    proc = subprocess.run(["pytest", "-q"], cwd=REPO_DIR, capture_output=True, text=True)
    return {"passed": proc.returncode == 0, "errors": proc.stdout + proc.stderr}

def _diff_against_main() -> str:
    return subprocess.run(["git", "-C", str(REPO_DIR), "diff", "main", "--", "."],
                          capture_output=True, text=True).stdout

def qa_check(spec: dict, tests: dict) -> dict:
    return _call_model("qa_critic.txt", spec=json.dumps(spec),
                       code=_diff_against_main(), test_results=json.dumps(tests))

def security_check(spec: dict) -> dict:
    """Read-only Security Critic vs the constitution. A plain API call keeps it
    clearly incapable of editing any file."""
    return _call_model("security_critic.txt",
                       applicable_constitution=json.dumps(spec["applicable_constitution"]),
                       constitution=CONSTITUTION, code=_diff_against_main())

def open_pull_request(qa: dict, security: dict) -> str:
    """Opens a PR — does NOT merge. A human approves the merge."""
    body = f"Automated change.\n\nQA: {json.dumps(qa)}\n\nSecurity: {json.dumps(security)}"
    r = requests.post(f"https://api.github.com/repos/{REPO_SLUG}/pulls", headers=GH,
                      json={"title": "Add daily transfer-limit validation",
                            "head": BRANCH, "base": "main", "body": body})
    return r.json()["html_url"]

def escalate_to_human(reason: str, state: dict) -> str:
    print(f"ESCALATED: {reason}\n{json.dumps(state, indent=2, ensure_ascii=False)}")
    return "escalated"


# ============================================================================
# Spec + the two Critics are plain model calls (judgment, no file edits).
# ============================================================================
def _call_model(prompt_file: str, **fields) -> dict:
    template = (PROMPTS / prompt_file).read_text()
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 4000,
              "messages": [{"role": "user", "content": template.format(**fields)}]})
    text = "".join(b["text"] for b in resp.json()["content"] if b["type"] == "text")
    return json.loads(text)


# ============================================================================
# THE LOOP. Codex writes; OUR code verifies, gates, caps, and escalates.
# ============================================================================
def review_spec(spec: dict) -> dict | None:
    """HUMAN-IN-THE-LOOP gate on the spec, BEFORE any code is written.

    Why here: the spec is the one thing the downstream gates cannot verify.
    Tests check code-vs-spec; the Security Critic checks code-vs-constitution;
    nothing checks spec-vs-business-intent. A wrong spec sails through every
    automated gate to a green PR. So a person confirms we're aiming at the right
    target; the loop then handles hitting it.

    Cost is low: reviewed ONCE per feature (not per iteration), and it's a short
    structured spec, not code. The expensive inner loop still runs unattended.

    Returns the approved (possibly human-edited) spec, or None to abort.
    Replace the console I/O with your real review channel (web UI, Slack, ticket).
    """
    print("\n=== SPEC REVIEW REQUIRED ===")
    print(json.dumps(spec, indent=2, ensure_ascii=False))
    choice = input("[a]pprove / [e]dit / [r]eject: ").strip().lower()
    if choice == "r":
        return None                       # abort: requirement is wrong / unclear
    if choice == "e":
        # Reviewer hands back a corrected spec (e.g. paste edited JSON, or load
        # from a file they amended). Keeps a small fix from becoming a rejection.
        edited = input("paste corrected spec JSON: ")
        return json.loads(edited)
    return spec                           # approved as-is


def run_loop(request: str) -> str:
    start = time.time()
    spec = _call_model("spec.txt", request=request, constitution=CONSTITUTION)

    # HUMAN GATE #1 (of 2): approve the target before the machine starts work.
    # (HUMAN GATE #2 is the PR approval before merge, at the end.)
    spec = review_spec(spec)
    if spec is None:
        return escalate_to_human("spec rejected by reviewer", {"request": request})

    _new_branch()
    last_error = ""

    for attempt in range(MAX_ITERATIONS):
        if time.time() - start > MAX_WALL_SECONDS:
            return escalate_to_human("time cap", {"spec": spec})

        # Step A: Codex edits files on disk to implement the spec.
        codex_actor(spec, last_error)

        # Step B: ENFORCE read-only-tests rule. Reject attempt if violated.
        ok, why = assert_no_protected_changes()
        if not ok:
            last_error = why
            continue

        # Step C: DETERMINISTIC GATE — we run the tests ourselves.
        tests = run_tests()
        if not tests["passed"]:
            last_error = f"Tests failed:\n{tests['errors']}"
            continue

        # Step D: QA Critic (only meaningful after tests pass).
        qa = qa_check(spec, tests)
        if qa["verdict"] == "fail":
            last_error = f"QA gaps:\n{json.dumps(qa['gaps'])}"
            continue

        # Step E: Security Critic vs the constitution (read-only).
        security = security_check(spec)
        if security["verdict"] == "fail":
            last_error = f"Constitution violations:\n{json.dumps(security['findings'])}"
            continue

        # All gates passed -> commit, push, open PR for a HUMAN to approve.
        commit_and_push()
        return open_pull_request(qa, security)

    return escalate_to_human("hit iteration cap", {"spec": spec, "last_error": last_error})


# --- small helpers (sketched) ----------------------------------------------
def _last_json_line(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        try: return json.loads(line)
        except json.JSONDecodeError: continue
    return {}

def _new_branch():
    subprocess.run(["git", "-C", str(REPO_DIR), "checkout", "-B", BRANCH, "main"])


if __name__ == "__main__":
    print("Result:", run_loop(
        "Before a transfer, check whether the customer's cumulative daily "
        "transfer amount exceeds their tier limit; if so, block it and return "
        "a clear error."))
