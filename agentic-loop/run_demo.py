"""run_demo.py — run the whole Kanban-driven flow locally (no Codex, no network).

Mirrors the proposal's TWO triggers with the human gate between them:

  1. Backlog -> Spec  : generate_spec_stage()  (AI writes spec, Slack notifies)
  2. HUMAN GATE #1     : the developer reviews and decides (approve / edit / reject)
                         -- this is OUTSIDE the loop; the card move is the approval
  3. Spec -> Dev       : agentic_loop()         (Actor<->Critic only, capped at 6)

Everything except the model calls and the external services is real: pytest
gates the code, `git diff` enforces the read-only-tests rule, the caps are live.

Usage:
    python3 run_demo.py                          # normal, developer approves -> PR
    python3 run_demo.py tamper                   # actor edits a test -> caught & reverted
    python3 run_demo.py never                    # loop fails 6x -> card back to Backlog
    python3 run_demo.py normal --decision reject # developer rejects spec -> back to Backlog
    python3 run_demo.py normal --decision edit   # developer edits spec, then approves
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import orchestrator
from connectors import slack_notify, taiga_board

HERE = Path(__file__).parent
CARD = 42
DEFAULT_REQUEST = (
    "Before a transfer, check whether the customer's cumulative daily transfer "
    "amount exceeds their tier limit; if so, block it and return a clear error."
)


def setup_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="bankapp_"))
    shutil.copytree(HERE / "demo_bankapp", repo / "demo_bankapp")
    shutil.copy(HERE / "constitution.md", repo / "constitution.md")
    for cmd in (["init", "-q", "-b", "main"],
                ["config", "user.email", "demo@example.com"],
                ["config", "user.name", "demo"],
                ["add", "-A"], ["commit", "-q", "-m", "initial bank app"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    return repo


def developer_review(spec: dict, decision: str, repo: Path) -> bool:
    """HUMAN GATE #1, simulated. In production this is a person in Taiga/Slack;
    the card move Spec->Dev IS the approval. Returns True to proceed to Dev."""
    print("\n" + "-" * 70)
    print("HUMAN GATE #1 — developer reviews the spec (approve / edit / reject)")
    print(f"  decision: {decision}")
    if decision == "reject":
        taiga_board.move_card(CARD, "Backlog", tag="spec-rejected", mode="mock")
        slack_notify.notify(f"Card #{CARD}: spec rejected -> returned to Backlog.", mode="mock")
        return False
    if decision == "edit":
        # Developer tweaks the spec summary before approving (kept trivial here).
        spec_path = repo / orchestrator.SPEC_FILE
        s = json.loads(spec_path.read_text())
        s["summary"] += " (clarified by reviewer)"
        spec_path.write_text(json.dumps(s, indent=2, ensure_ascii=False))
        print("  developer edited the spec, then approves")
    print("  approved -> moving card Spec -> Dev (this move triggers the loop)")
    print("-" * 70)
    return True


def main():
    args = sys.argv[1:]
    scenario = next((a for a in args if not a.startswith("-")), "normal")
    decision = "approve"
    if "--decision" in args:
        decision = args[args.index("--decision") + 1]

    repo = setup_repo()
    print(f"repo: {repo}   scenario: {scenario}   decision: {decision}")
    print("=" * 70)
    print("TRIGGER 1 — card moved Backlog -> Spec")
    spec = orchestrator.generate_spec_stage(
        DEFAULT_REQUEST, repo, mode="mock", card_ref=CARD)

    if not developer_review(spec, decision, repo):
        print("\nRESULT: spec rejected; no code written.")
        shutil.rmtree(repo, ignore_errors=True)
        return

    print("\n" + "=" * 70)
    print("TRIGGER 2 — card moved Spec -> Dev (Agentic Loop starts)")
    result = orchestrator.agentic_loop(repo, mode="mock", scenario=scenario, card_ref=CARD)

    print("=" * 70 + "\nRESULT:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
