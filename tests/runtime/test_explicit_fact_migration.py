"""Facts survive related skills; migration requires an accepted, explicit link.

Replaces the former global text-overlap invariant, which incorrectly treated
the factual premise of a workflow as a duplicate workflow instruction.
"""
import json
import copy
from types import SimpleNamespace as NS

import pytest

from mellowday.personal_assistant.tools import build_fact_provider, execute_tool
from mellowday.runtime.agent import Agent
from mellowday.runtime import skills
from mellowday.runtime import events
from mellowday.runtime.memory import FACT_REMINDER_MARKER, SUPERSEDED_FACTS_MARKER, SUPERSEDED_FACTS_RULE
from mellowday.storage.store import Store


def make_agent(store, approved=True):
    async def executor(name, arguments):
        return await execute_tool(store, name, arguments)

    async def confirm(summary):
        return approved

    agent = Agent(model="test-model", api_base="http://127.0.0.1:9/v1", api_key="test",
                  fact_provider=build_fact_provider(store), tool_executor=executor,
                  confirm_fn=confirm)
    return agent


def create_fact(store):
    return store.create_record("memories", {
        "title": "Work schedule",
        "detail": "I finish work every weekday at six in the evening",
        "meta": {"memory_kind": "fact"},
    })


@pytest.mark.anyio
@pytest.mark.parametrize("disabled", [False, True])
async def test_related_fact_survives_enabled_or_disabled_skill(disabled):
    store = Store()
    skills.reset_skill_cache()
    skills.create_skill_file(name="evening-exercise", description="Plan exercise after work",
                             instructions="When I finish work every weekday at six in the evening, plan exercise afterwards.")
    if disabled:
        skills.disable_skill("evening-exercise")
    agent = make_agent(store)
    result = await execute_tool(store, "remember_fact", {
        "label": "Work schedule", "kind": "fact",
        "content": "I finish work every weekday at six in the evening",
    })
    agent._note_facts_from_tool_result("remember_fact", result)
    record_id = json.loads(result)["record"]["id"]
    assert store.get_record("memories", record_id)["status"] == "active"
    assert any(row["id"] == record_id for row in await agent.fact_provider(""))
    skills.reset_skill_cache()


@pytest.mark.anyio
@pytest.mark.parametrize("action,approved,linked,expected", [
    ("add", True, True, "superseded"),
    ("merge", True, True, "superseded"),
    ("discard", True, True, "active"),
    ("add", False, True, "active"),
    ("add", True, False, "active"),
])
async def test_only_confirmed_write_with_explicit_source_id_migrates(monkeypatch, action, approved, linked, expected):
    store = Store()
    fact = create_fact(store)
    agent = make_agent(store, approved)

    async def ingest(**kwargs):
        assert kwargs["source_facts"][0]["id"] == fact["id"]
        allowed = await kwargs["confirm_write"]("Migrate source memory " + fact["id"])
        return {"ok": allowed, "action": action, "skill": "work-planning",
                "candidate": {"source_memory_ids": [fact["id"]] if linked else []}}

    monkeypatch.setattr(skills, "online_ingest", ingest)
    await agent._run_online_skill_evolution({"messages": [{"role": "user", "content": "Use this as a workflow"}]})
    assert store.get_record("memories", fact["id"])["status"] == expected


@pytest.mark.anyio
async def test_edit_during_confirmation_is_not_overwritten(monkeypatch):
    store = Store()
    fact = create_fact(store)
    agent = make_agent(store)

    async def ingest(**kwargs):
        await kwargs["confirm_write"]("Migrate " + fact["id"])
        store.update_record("memories", fact["id"], {"detail": "I now finish work at five"})
        return {"ok": True, "action": "add", "skill": "work-planning",
                "candidate": {"source_memory_ids": [fact["id"]]}}

    monkeypatch.setattr(skills, "online_ingest", ingest)
    await agent._run_online_skill_evolution({"messages": [{"role": "user", "content": "Use this as a workflow"}]})
    current = store.get_record("memories", fact["id"])
    assert current["status"] == "active"
    assert current["detail"] == "I now finish work at five"


@pytest.mark.anyio
async def test_unknown_source_id_does_not_migrate_other_facts(monkeypatch):
    store = Store()
    fact = create_fact(store)
    agent = make_agent(store)

    async def ingest(**kwargs):
        await kwargs["confirm_write"]("Migrate unknown record")
        return {"ok": True, "action": "add", "skill": "work-planning",
                "candidate": {"source_memory_ids": ["missing"]}}

    monkeypatch.setattr(skills, "online_ingest", ingest)
    await agent._run_online_skill_evolution({"messages": [{"role": "user", "content": "Use this as a workflow"}]})
    assert store.get_record("memories", fact["id"])["status"] == "active"


@pytest.mark.anyio
async def test_migrated_fact_is_explicitly_invalidated_in_next_model_request(monkeypatch):
    store = Store()
    rule = "When planning, check fixed events before selecting three priorities."
    source = store.create_record("memories", {
        "title": "Planning preference", "detail": rule,
        "meta": {"memory_kind": "preference"},
    })
    agent = make_agent(store)
    calls = []

    async def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))

        async def stream():
            yield NS(choices=[NS(delta=NS(content=rule, tool_calls=None), finish_reason=None)], usage=None)
            yield NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="stop")], usage=None)

        return stream()

    agent._openai_client = NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr(agent, "_online_evolution_enabled", lambda: False)
    with events.use_sink(lambda event: None):
        await agent.chat("Help with planning priorities")
    assert source["id"] in agent._observed_facts

    agent._migrate_confirmed_source_facts({
        "ok": True, "action": "add", "skill": "planning",
        "candidate": {"source_memory_ids": [source["id"]]},
    }, [source])
    assert store.get_record("memories", source["id"])["status"] == "superseded"

    # No skill is loaded: the historical preference must not silently replace it.
    with events.use_sink(lambda event: None):
        await agent.chat("Continue planning priorities")
    messages = calls[-1]["messages"]
    assert any(m["role"] == "assistant" and m.get("content") == rule for m in messages)
    latest = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    current, invalidated = latest.split(FACT_REMINDER_MARKER, 1)[1].split(SUPERSEDED_FACTS_MARKER, 1)
    assert rule not in current
    assert rule in invalidated
    assert SUPERSEDED_FACTS_RULE in invalidated
