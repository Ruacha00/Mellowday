"""Gate evidence distinguishes explicit migration from mere textual overlap."""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("gate_l3_learning")


def fact(key, detail):
    return {"id": key, "title": key, "detail": detail, "status": "active", "meta": {}}


def test_gate_scenario_requests_exact_workflow_and_preserves_objective(gate, isolated_data_dir):
    from mellowday.storage.store import Store

    store = Store(isolated_data_dir)
    scenario = gate.seed_migration_scenario(store)
    rows = store.list_records("memories")
    assert len(rows) == 2
    workflow_id = scenario["source_memory_ids"][0]
    objective_id = scenario["objective_memory_id"]
    assert workflow_id != objective_id
    assert scenario["message"].startswith(gate.CORRECTION)
    assert "ID " + workflow_id + " 迁移" in scenario["message"]
    assert "ID " + objective_id in scenario["message"]
    assert "保留为有效事实，不要迁移或修改" in scenario["message"]
    assert all(row["status"] == "active" for row in rows)
    workflow = store.get_record("memories", workflow_id)
    events, confirmations = proposal(workflow)
    after = [dict(row) for row in rows]
    for row in after:
        if row["id"] == workflow_id:
            row.update(status="superseded", meta={"superseded_by_skill": "planning"})
    assert gate.assess_confirmed_migration(rows, after, events, confirmations)["status"] == "passed"


def proposal(row):
    summary = "习惯：planning\n同时把以下事实迁移为技能规则（原记录保留）：\n- ID %s | %s\n%s" % (
        row["id"], row["title"], row["detail"])
    return [{"type": "skill_candidate_proposed", "skill": "planning", "summary": summary},
            {"type": "skill_candidate_applied", "skill": "planning"}], [{"summary": summary}]


def test_only_explicit_source_migrates_and_related_fact_survives(gate):
    source = fact("rule", "先固定日程再三个重点任务")
    objective = fact("objective", "周三固定日程是10点开会")
    migrated = {**source, "status": "superseded", "meta": {"superseded_by_skill": "planning"}}
    events, confirmations = proposal(source)
    verdict = gate.assess_confirmed_migration([source, objective], [migrated, objective], events, confirmations)
    assert verdict["status"] == "passed"
    assert verdict["source_memory_ids"] == ["rule"]


def test_no_proposal_is_inconclusive_even_when_text_overlaps(gate):
    objective = fact("objective", "周三固定日程是10点开会")
    verdict = gate.assess_confirmed_migration([objective], [objective], [], [])
    assert verdict["status"] == "inconclusive"


@pytest.mark.anyio
async def test_no_learned_rule_reports_each_check_once(gate, monkeypatch, isolated_data_dir):
    from mellowday import paths
    from mellowday.storage.store import Store

    class Report:
        def __init__(self):
            self.names = []

        def check(self, name, *args, **kwargs):
            self.names.append(name)

        def inconclusive(self, name, *args, **kwargs):
            self.names.append(name)

    async def turn(registry, session, message, **kwargs):
        return {"session_id": session, "message": message, "reply": "",
                "learning": [], "confirmations": [], "errors": [], "tools": [],
                "tool_results": [], "warnings": [], "notices": [], "event_types": []}

    monkeypatch.setattr(gate.gc, "run_turn", turn)
    monkeypatch.setattr(gate.gc, "session_freshness", lambda *args: {"fresh": True})
    run = SimpleNamespace(data_dir=isolated_data_dir, session_id=lambda phase, index: phase)
    report = Report()
    await gate.run_l3_checks(
        run, report, object(), Store(isolated_data_dir), None, paths,
        SimpleNamespace(calls=[]), 2, [], {}, [], {},
    )
    assert "l3.correction_produces_a_rule" in report.names
    assert report.names.count("l3.correction_migrates_only_confirmed_sources") == 1
    assert len(report.names) == len(set(report.names))


def test_unselected_fact_migration_fails(gate):
    objective = fact("objective", "周三固定日程是10点开会")
    migrated = {**objective, "status": "superseded"}
    assert gate.assess_confirmed_migration([objective], [migrated], [], [])["status"] == "failed"


def invalidated_payload(*, current="", declaration=True, marker=True):
    header = "Recalled facts about the user (current values from the memory store):"
    obsolete = "Facts that were current earlier in this conversation and are NOT current any more:"
    prohibition = ("Those superseded values are history only: never repeat them as the user's current "
                   "situation, even when an earlier reply, tool result or folded summary mentions them.")
    block = "<system-reminder>\n" + header + "\n" + current + "\n"
    block += (obsolete if marker else "Old notes") + "\n- old value: RULE-PROBE\n"
    block += (prohibition if declaration else "") + "\n</system-reminder>"
    return {"payload_text": json.dumps({"messages": [{"role": "user", "content": block}]})}


def test_same_session_explicit_invalidated_quote_is_allowed(gate):
    call = invalidated_payload()
    result = gate.same_session_fact_boundary([call], ["RULE-PROBE"])
    assert result["ok"]
    assert result["allowed_invalidated_references"]
    assert result["semantics"] == "same-session-fact-boundary-v2"
    # The same payload still fails the unchanged new-session zero-leak rule.
    assert gate.gc.payload_probe_locations([call], ["RULE-PROBE"])["in_superseded_block"]


@pytest.mark.parametrize("kwargs", [{"current": "- current rule: RULE-PROBE"},
                                   {"declaration": False}, {"marker": False}])
def test_same_session_current_rule_or_uncontrolled_quote_fails(gate, kwargs):
    result = gate.same_session_fact_boundary([invalidated_payload(**kwargs)], ["RULE-PROBE"])
    assert not result["ok"]
    assert result["errors"]


def test_invalid_second_reminder_cannot_hide_behind_valid_one(gate):
    valid = json.loads(invalidated_payload()["payload_text"])["messages"][0]
    invalid = json.loads(invalidated_payload(declaration=False)["payload_text"])["messages"][0]
    call = {"payload_text": json.dumps({"messages": [valid, invalid]})}
    assert not gate.same_session_fact_boundary([call], ["RULE-PROBE"])["ok"]


@pytest.mark.parametrize("missing", ["original", "confirmation", "applied", "snapshot"])
def test_migration_requires_complete_confirmed_evidence(gate, missing):
    source = fact("rule", "先固定日程再三个重点任务")
    migrated = {**source, "status": "superseded", "meta": {"superseded_by_skill": "planning"}}
    events, confirmations = proposal(source)
    if missing == "original":
        events[0]["summary"] = events[0]["summary"].replace(source["detail"], "")
        confirmations[0]["summary"] = events[0]["summary"]
    elif missing == "confirmation":
        confirmations = []
    elif missing == "applied":
        events = events[:1]
    else:
        migrated["detail"] = "changed while confirmation was open"
    assert gate.assess_confirmed_migration([source], [migrated], events, confirmations)["status"] == "failed"
