"""Spec Drafting agent: prompt assembly, LLM call, output validation.

Validation (infra doc §4): frontmatter parses, `# Feature` present, ≥1 `AC-`
line, every cited §n exists in the constitution. Failure → retry once with the
error appended → else comment on the card and leave it in Spec Drafting.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent.parent / "skills" / "prompts" / "spec_drafter.txt"


@dataclass
class ValidationError(Exception):
    problems: list[str]

    def __str__(self) -> str:
        return "; ".join(self.problems)


def constitution_sections(constitution_md: str) -> set[int]:
    return {int(m) for m in re.findall(r"§(\d+)", constitution_md)}


def validate_spec(spec_md: str, constitution_md: str) -> None:
    problems: list[str] = []

    fm = re.match(r"\A---\n(.*?)\n---\n", spec_md, re.DOTALL)
    if not fm:
        problems.append("missing or malformed frontmatter block")
    else:
        keys = dict(
            line.split(":", 1) for line in fm.group(1).splitlines() if ":" in line
        )
        for required in ("story", "spec_version", "generated"):
            if required not in keys:
                problems.append(f"frontmatter missing '{required}'")

    if not re.search(r"^# Feature: \S", spec_md, re.MULTILINE):
        problems.append("missing '# Feature:' heading")

    if not re.search(r"^- AC-\d+:", spec_md, re.MULTILINE):
        problems.append("no AC- lines found")

    known = constitution_sections(constitution_md)
    cited = {int(m) for m in re.findall(r"§(\d+)", spec_md)}
    bogus = sorted(cited - known)
    if bogus:
        problems.append(f"cited constitution clause(s) not found: {bogus}")

    if problems:
        raise ValidationError(problems)


def has_open_questions(spec_md: str) -> bool:
    """True when an Open questions section survives with content — blocks move ③."""
    m = re.search(r"^## Open questions\s*\n(.*?)(?=^## |\Z)", spec_md,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return False
    body = re.sub(r"<[^>]*>", "", m.group(1))          # template placeholders don't count
    return bool(re.search(r"^\s*[-*]\s*\S", body, re.MULTILINE))


def build_input(subject: str, description: str, constitution_md: str,
                story_ref: str, spec_version: int,
                previous_spec: str | None = None,
                feedback_comments: list[str] | None = None) -> str:
    parts = [
        f"【卡片標題】{subject}",
        f"【故事內容】\n{description}",
        f"【story ref】{story_ref}",
        f"【spec_version】{spec_version}",
        f"【憲法 constitution】\n{constitution_md}",
    ]
    if previous_spec:
        parts.append(f"【前一版規格（請依回饋修訂）】\n{previous_spec}")
    if feedback_comments:
        parts.append("【審查回饋】\n" + "\n---\n".join(feedback_comments))
    return "\n\n".join(parts)


def call_llm(system_prompt: str, user_input: str, timeout: int = 300) -> str:
    """Demo topology: shell out to the host's authenticated claude CLI."""
    r = subprocess.run(
        ["claude", "-p", "--append-system-prompt", system_prompt],
        input=user_input, capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({r.returncode}): {r.stderr[-500:]}")
    return r.stdout.strip()


def draft_spec(subject: str, description: str, constitution_md: str,
               story_ref: str, spec_version: int = 1,
               previous_spec: str | None = None,
               feedback_comments: list[str] | None = None,
               llm=call_llm) -> str:
    """One LLM call, validated; retry once with the error appended."""
    system = PROMPT_PATH.read_text()
    user = build_input(subject, description, constitution_md, story_ref,
                       spec_version, previous_spec, feedback_comments)
    spec = llm(system, user)
    try:
        validate_spec(spec, constitution_md)
        return spec
    except ValidationError as e:
        retry_input = (f"{user}\n\n【上一次輸出未通過驗證，原因：{e}。"
                       f"請修正後重新輸出完整規格。】\n{spec}")
        spec = llm(system, retry_input)
        validate_spec(spec, constitution_md)   # second failure propagates
        return spec
