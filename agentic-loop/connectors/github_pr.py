"""GitHub connector — opens a Pull Request. NEVER merges.

Merging is HUMAN GATE #2: a person reviews the PR (which carries the QA and
Security reports in its body) and clicks merge. The loop only ever opens it.

In mode="mock" this is a dry run: it prints what it WOULD do and returns a
placeholder URL, so the demo needs no GitHub token or network. In mode="codex"
(real) it pushes the branch and calls the GitHub REST API.

Env for real mode:
  GITHUB_TOKEN  - repo-scoped token (push branch, open PR)
  REPO_SLUG     - e.g. "yourorg/bankapp"
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _pr_body(qa: dict, security: dict) -> str:
    return (
        "Automated change produced by the controlled Actor<->Critic loop.\n\n"
        "**This PR is NOT auto-merged.** A human reviews and merges (human gate #2).\n\n"
        f"### QA Critic\n```json\n{json.dumps(qa, indent=2)}\n```\n\n"
        f"### Security Critic (vs constitution)\n```json\n{json.dumps(security, indent=2)}\n```\n"
    )


def open_pull_request(*, branch: str, qa: dict, security: dict,
                      mode: str = "mock", repo_dir: Path | None = None,
                      base: str = "main") -> str:
    body = _pr_body(qa, security)

    if mode == "mock":
        print("    [github dry-run] would push branch and open PR:")
        print(f"      head={branch} base={base}")
        print("      body carries QA + Security reports for human review")
        return f"https://github.com/EXAMPLE/bankapp/pull/0  (dry-run, branch={branch})"

    # --- real mode --------------------------------------------------------
    import requests  # local import so mock mode needs no dependency

    repo_slug = os.environ["REPO_SLUG"]
    token = os.environ["GITHUB_TOKEN"]
    if repo_dir is not None:
        subprocess.run(["git", "-C", str(repo_dir), "push", "-u", "origin", branch], check=True)
    r = requests.post(
        f"https://api.github.com/repos/{repo_slug}/pulls",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json={"title": "Add daily transfer-limit validation",
              "head": branch, "base": base, "body": body},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["html_url"]
