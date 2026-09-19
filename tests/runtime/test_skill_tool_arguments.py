"""Regression tests for the skill tool argument handling.

A real-model gate found the habit loop completely dead: the model sent
{"name": ...} while the executor read only inp["skill_name"], so every skill
invocation returned 'Unknown skill: ' with the name silently dropped. The
failure looked like a retrieval problem, not an argument mismatch.
"""
from __future__ import annotations

import pytest

from mellowday.runtime.agent import Agent


@pytest.mark.parametrize(
    "arguments",
    [
        {"skill_name": "每周回顾"},
        {"name": "每周回顾"},
        {"skill": "每周回顾"},
        {"name": "  每周回顾  "},
    ],
)
def test_skill_name_is_resolved_from_common_argument_keys(arguments):
    assert Agent._skill_name_from_arguments(arguments) == "每周回顾"


@pytest.mark.parametrize(
    "arguments",
    [{}, {"skill_name": ""}, {"skill_name": "   "}, {"name": 123}, {"other": "x"}],
)
def test_missing_skill_name_resolves_to_empty(arguments):
    assert Agent._skill_name_from_arguments(arguments) == ""


@pytest.mark.anyio
async def test_unknown_skill_error_names_the_arguments_received():
    # A bare 'Unknown skill: ' is what made the original bug hard to see.
    agent = Agent(model="deepseek-chat", api_base="https://example.invalid/v1", api_key="x")
    message = await agent._execute_skill_tool({"name": "不存在的技能"})
    assert "不存在的技能" in message
    assert "Arguments received" in message
    assert "skill_name" in message


@pytest.mark.anyio
async def test_error_mentions_when_no_name_was_supplied_at_all():
    agent = Agent(model="deepseek-chat", api_base="https://example.invalid/v1", api_key="x")
    message = await agent._execute_skill_tool({"args": "x"})
    assert "no name supplied" in message
