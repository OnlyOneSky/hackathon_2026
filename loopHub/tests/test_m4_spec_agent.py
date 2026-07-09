import pytest

from hub.spec_agent import (ValidationError, draft_spec, has_open_questions,
                            validate_spec)

CONSTITUTION = """# Constitution
§1 (金額精度) 所有金額用 Decimal。
§2 (稽核) 拒絕交易必須留稽核紀錄。
§3 (資安) 不記錄完整帳號。
"""

GOOD_SPEC = """---
story: bankapp#42
spec_version: 1
generated: 2026-07-09T12:00:00Z
---
# Feature: Daily cumulative transfer limit

## Summary
轉帳加上單日累計限額。

## Acceptance criteria
- AC-1: 單日累計超過 100000 時，第 N 筆轉帳被拒絕並留稽核紀錄（§2）
- AC-2: 剛好等於限額的轉帳成功

## Applicable constitution clauses
§1 (金額精度), §2 (稽核)

## Out of scope
- 每月限額
"""


def test_good_spec_validates():
    validate_spec(GOOD_SPEC, CONSTITUTION)


@pytest.mark.parametrize("mutation,expected", [
    (lambda s: s.replace("---\n", "", 1), "frontmatter"),
    (lambda s: s.replace("# Feature: Daily", "# Feat: Daily"), "Feature"),
    (lambda s: s.replace("- AC-1:", "- ").replace("- AC-2:", "- "), "AC-"),
    (lambda s: s.replace("（§2）", "（§9）"), "not found"),
])
def test_bad_specs_rejected(mutation, expected):
    with pytest.raises(ValidationError) as e:
        validate_spec(mutation(GOOD_SPEC), CONSTITUTION)
    assert expected in str(e.value)


def test_open_questions_detection():
    assert not has_open_questions(GOOD_SPEC)
    assert has_open_questions(GOOD_SPEC + "\n## Open questions\n- 限額含手續費嗎？\n")
    # template placeholder alone does not count
    assert not has_open_questions(GOOD_SPEC + "\n## Open questions\n- <anything ambiguous>\n")


def test_draft_spec_retries_once_then_succeeds():
    calls = []

    def fake_llm(system, user):
        calls.append(user)
        return "garbage" if len(calls) == 1 else GOOD_SPEC

    spec = draft_spec("限額", "story", CONSTITUTION, "bankapp#42", llm=fake_llm)
    assert spec == GOOD_SPEC
    assert len(calls) == 2 and "未通過驗證" in calls[1]


def test_draft_spec_double_failure_raises():
    def bad_llm(system, user):
        return "garbage"

    with pytest.raises(ValidationError):
        draft_spec("限額", "story", CONSTITUTION, "bankapp#42", llm=bad_llm)
