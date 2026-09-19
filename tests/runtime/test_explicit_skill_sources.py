"""Only provided fact identities may be proposed for confirmed migration."""
import json

import pytest

from mellowday.runtime.skills import create_skill_file, discover_skills, reset_skill_cache
from mellowday.runtime.skills.online_skill_evolution import online_ingest


@pytest.fixture(autouse=True)
def clean_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


def query_for(action, ids, payloads):
    async def query(system, payload):
        payloads.append(json.loads(payload))
        if "Extractor" in system:
            return json.dumps({"skills": [{
                "name": "planning", "description": "Daily planning procedure",
                "instructions": "- Reserve a lunch break.",
                "source_memory_ids": ids,
            }]})
        return json.dumps({"action": action, "target_skill": "planning"})
    return query


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["add", "merge"])
async def test_migration_ids_are_bound_to_snapshot_and_visible_before_writing(action):
    if action == "merge":
        create_skill_file(name="planning", description="Daily planning procedure", instructions="- Check calendar appointments.")
    original = "Reserve a lunch break. " + "Original context. " * 40
    facts = [
        {"id": "fact-1", "title": "Planning rule", "detail": original, "status": "active"},
        {"id": "expired", "detail": "Old instruction", "status": "expired"},
    ]
    payloads, confirmations = [], []

    async def confirm(summary):
        confirmations.append(summary)
        assert "ID fact-1" in summary and original in summary
        assert "invented" not in summary and "expired" not in summary
        return True

    result = await online_ingest(
        messages=[{"role": "user", "content": "From now on move my planning rule into a skill."}],
        side_query=query_for(action, ["fact-1", "invented", "expired", "fact-1"], payloads),
        confirm_write=confirm, source_facts=facts,
    )
    assert result["ok"] and result["written"] and result["confirmed"]
    assert result["candidate"]["source_memory_ids"] == ["fact-1"]
    assert len(confirmations) == 1
    assert payloads[0]["source_facts"] == [facts[0]]
    assert facts[0]["status"] == "active"  # Only the caller performs a validated migration.


@pytest.mark.anyio
@pytest.mark.parametrize("has_confirmer", [False, True])
async def test_source_migration_is_never_written_without_approval(has_confirmer):
    async def deny(summary):
        return False

    result = await online_ingest(
        messages=[{"role": "user", "content": "From now on use my planning rule."}],
        side_query=query_for("add", ["fact-1"], []),
        confirm_write=deny if has_confirmer else None,
        source_facts=[{"id": "fact-1", "detail": "Reserve a lunch break.", "status": "active"}],
    )
    assert result["action"] == "add_denied"
    assert not result["written"]
    assert discover_skills() == []


@pytest.mark.anyio
async def test_ids_not_provided_by_caller_cannot_become_migration_sources():
    async def approve(summary):
        assert "ID invented" not in summary
        return True

    result = await online_ingest(
        messages=[{"role": "user", "content": "From now on reserve a lunch break."}],
        side_query=query_for("add", ["invented"], []), confirm_write=approve,
    )
    assert result["candidate"]["source_memory_ids"] == []
