"""Regressions for preserving explicit rules and the latest request scope."""
import pytest

from mellowday.runtime.skills.instruction_merge import merge_instructions
from mellowday.runtime.skills.request_scope import classify_request_scope


def test_similar_parallel_rules_both_survive_complete_proposal():
    morning = "- Before scheduling morning tasks, check the calendar for fixed appointments."
    evening = morning.replace("morning", "evening")
    result = merge_instructions(existing_body=morning, proposed_body=morning + "\n" + evening)
    assert result["rules_body"].splitlines() == [morning, evening]
    assert result["removed"] == [] and result["revised"] == []


@pytest.mark.parametrize("old,new", [("three", "two"), ("always", "never")])
def test_small_constraint_change_is_not_semantic_duplicate(old, new):
    previous = "- When planning my work day always include three important tasks after checking the calendar for appointments and before scheduling meals exercise rest breaks or leisure time."
    replacement = previous.replace(old, new)
    result = merge_instructions(existing_body=previous, new_instructions=replacement)
    assert result["changed"] is True
    assert result["rules_body"].splitlines() == [previous, replacement]


def test_superseded_requires_verbatim_rule_not_punctuation_normalization():
    previous = "- Compare A+B with C."
    result = merge_instructions(existing_body=previous, superseded=["- Compare AB with C."])
    assert result["rules_body"] == previous
    assert result["changed"] is False


@pytest.mark.parametrize("history,latest,expected", [
    ("以后规划只列三个重点任务。", "这次临时列六个重点任务。", False),
    ("这次不用记住，我只想看一句话。", "以后每天规划先列固定日程。", True),
    ("不用保存这次的要求。", "每次都先给结论。", True),
    ("From now on always list three tasks.", "This time list six tasks.", False),
])
def test_latest_explicit_scope_wins(history, latest, expected):
    result = classify_request_scope([
        {"role": "user", "content": history},
        {"role": "assistant", "content": "OK"},
        {"role": "user", "content": latest},
    ])
    assert result["learnable"] is expected
