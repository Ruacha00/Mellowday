"""L3 gate for the learning loop itself (P4 core acceptance).

The behavioural gate proves a skill changes behaviour once it exists. This one
asks the harder question: does an explicit user correction actually become a
durable rule that a brand new session follows? That path is model-driven -
candidate extraction, a confirmation the user must approve, then retrieval in a
later session - so only a real model can exercise it.

Method rules this gate enforces (see docs/evidence/P3-P4-l3-gate-method.md):

  * one isolated data directory per run (database, sessions, skills, skill
    archive, evolution records, config.json), pinned before mellowday is
    imported; the machine's real data directory is only stat-ed, before and
    after, to show it was not touched;
  * every session id carries the run id and is asserted to be empty before use;
  * a correction is only accepted as a learned rule together with the artifact:
    a real SKILL.md inside the run directory, its version, its instructions and
    the provenance record of the write;
  * a denied confirmation must write nothing and must be visible - and if no
    candidate was proposed at all, the check is inconclusive, never a pass;
  * the behavioural side is judged against the rule's requirements and against
    real records (a fixed calendar entry seeded into SQLite must be reflected in
    the plan), never against a keyword appearing somewhere in the reply;
  * a pre-learning control and a post-disable sample bracket the contrast, so
    "the new session follows the rule" cannot be satisfied by prose the model
    would have written anyway.

Run:  python scripts/gate_l3_learning.py
      python scripts/gate_l3_learning.py --offline
      python scripts/gate_l3_learning.py --selfcheck

Exit codes: 0 all checks passed, 1 a check failed or was inconclusive,
2 the L3 part was not run (no credentials or --offline).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any

import gate_common as gc

REPO = Path(__file__).resolve().parents[1]

GATE = "l3-learning"
REPORT_PATH = REPO / "docs" / "evidence" / "raw" / "gate-l3-learning-report.json"

PLAN_ASK = "帮我规划一下明天要做的事：明天有三件事要办——写季度报告、开项目周会、买生日礼物。"
"""The turn the correction answers; it also seeds the learning window."""
CORRECTION = "不对。以后帮我规划的时候，必须先列出当天已有的固定日程，然后只排三个重点任务，不要一次列十几条。"
COMPARE_ASK = "帮我规划一下明天要做的事。"
"""The turn the before/after comparison is measured on.

It deliberately does not enumerate the tasks: with six real to-dos already in
the database, only the rule makes the model pick exactly three and lead with
the fixed schedule. A question that lists the tasks itself would let a rule-less
reply match the rule's shape.
"""
RULE_TERMS = ("固定日程", "重点任务")
SEED_EVENT_TITLE = "每日站会"
SEED_EVENT_LOCAL = "09:30"
SEED_TODOS = ("写季度报告", "开项目周会", "买生日礼物", "整理收件箱", "续保车险", "预约体检")
LEARNED_SPEC = {
    "sections": ["固定日程", "重点任务"],
    "terms": (SEED_EVENT_TITLE,),
    "any_terms": {"name": "real_todos", "min": 3, "terms": list(SEED_TODOS)},
    "item_limit": {"section": "重点任务", "min": 3, "max": 3},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attempts", type=int, default=2, help="post-learning samples (default 2)")
    parser.add_argument("--run-root", default=str(gc.DEFAULT_RUN_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--json-out", default="", help="report path (default: the stable path for an L3 run, the run directory otherwise)")
    parser.add_argument("--source-data-dir", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--no-selfcheck", dest="selfcheck", action="store_false")
    parser.add_argument("--no-keep-run-dir", dest="keep", action="store_false", default=True)
    return parser.parse_args()


def tomorrow_local_iso(hour: int, minute: int) -> str:
    now = datetime.now().astimezone()
    target = datetime.combine((now + timedelta(days=1)).date(), clock_time(hour, minute))
    return target.replace(tzinfo=now.tzinfo).isoformat()


async def main() -> int:
    args = parse_args()
    attempts = max(1, int(args.attempts))

    run = gc.RunContext(
        GATE,
        run_root=args.run_root,
        run_id=args.run_id,
        keep=args.keep,
        source_data_dir=args.source_data_dir or None,
    ).prepare()
    report = gc.Report(GATE, run)
    gc.ensure_src_on_path()

    print("run:  " + run.run_id)
    print("data: " + str(run.data_dir))
    print("real: " + str(run.source_data_dir) + "  (never written to)")

    initial = run.isolated_state()
    report.check(
        "isolation.run_directory_starts_empty",
        not initial["sessions"] and not initial["skills"] and not initial["has_database"],
        detail=initial,
    )

    seeded = run.seed_model_config()
    print("model: %s  endpoint: %s  key: %s" % (
        seeded["model"], seeded["api_base"],
        "present(" + seeded["api_key_fingerprint"] + ")" if seeded["api_key_present"] else "absent",
    ))

    if args.selfcheck:
        gc.run_predicate_selfcheck(report)

    from mellowday import config, paths  # noqa: E402  (after the run directory is pinned)
    from mellowday.storage.store import Store  # noqa: E402
    from mellowday.web_app.service import SessionRegistry  # noqa: E402
    from mellowday.runtime.prompt import build_system_prompt  # noqa: E402
    from mellowday.runtime.skills import disable_skill, list_skills, reset_skill_cache  # noqa: E402

    store = Store(data_dir=run.data_dir)
    registry = SessionRegistry(store=store)

    baseline = [entry for entry in list_skills()]
    print("baseline skills: %s" % [entry.get("name") for entry in baseline])

    offline_evidence = await gc.offline_transaction_checks(store, report)
    l3_extra: dict[str, object] = {"offline": offline_evidence}

    # A real fixed schedule, so "list today's existing fixed schedule" can be
    # verified against a database row instead of against model prose.
    seeded_event = await gc.call_tool(
        store,
        "create_calendar_event",
        {
            "title": SEED_EVENT_TITLE,
            "due_at": tomorrow_local_iso(9, 30),
            "status": "scheduled",
            "detail": "每天早上的固定站会",
        },
    )
    seeded_rows = [row for row in gc.db_rows(store, "calendar") if row.get("title") == SEED_EVENT_TITLE]
    report.check(
        "deterministic.fixed_schedule_seeded_as_a_real_row",
        bool(seeded_event.get("ok")) and len(seeded_rows) == 1,
        detail={
            "tool_result": {key: seeded_event.get(key) for key in ("ok", "id", "due_at", "due_at_local")},
            "rows": len(seeded_rows),
        },
    )

    seeded_todos = {}
    for title in SEED_TODOS:
        result = await gc.call_tool(
            store, "create_todo", {"title": title, "due_at": tomorrow_local_iso(0, 0), "status": "open"}
        )
        seeded_todos[title] = str(result.get("id") or "")
    rows_now = gc.db_rows(store, "todos")
    seeded_titles = [str(row.get("title") or "") for row in rows_now if str(row.get("title") or "") in SEED_TODOS]
    report.check(
        "deterministic.business_baseline_seeded_as_real_rows",
        sorted(seeded_titles) == sorted(SEED_TODOS),
        detail={
            "seeded": seeded_todos,
            "rows": [{"title": row.get("title"), "due_at": row.get("due_at")} for row in rows_now],
            "note": (
                "six real to-dos, so 'only the three most important ones' is an "
                "observable constraint rather than a restatement of the input"
            ),
        },
    )

    recorder = gc.ModelCallRecorder()
    status = {"status": "not_run", "reason": "", "model": seeded["model"], "api_base": seeded["api_base"]}
    if not seeded["api_key_present"]:
        status["reason"] = "no credential available (MELLOWDAY_API_KEY and the local config are both empty)"
    elif args.offline:
        status["reason"] = "offline mode requested"

    if status["reason"]:
        reason = status["reason"]
        report.pending("l3.pre_learning_control_does_not_follow_the_rule", reason)
        report.pending("l3.correction_produces_a_rule", reason)
        report.pending("deterministic.rule_text_covers_the_correction", reason)
        report.pending("deterministic.rule_enters_a_new_session_prompt", reason)
        report.pending("l3.correction_does_not_duplicate_the_rule_into_the_memory_store", reason)
        report.pending("l3.a_new_session_follows_the_learned_rule", reason)
        report.pending("l3.denied_confirmation_writes_nothing", reason)
        report.pending("deterministic.disabled_rule_leaves_the_prompt", reason)
        report.pending("l3.correction_migrates_only_confirmed_sources", reason)
        report.pending("l3.disabled_rule_stops_changing_behaviour (sampled %d)" % attempts, reason)
        report.pending("l3.disable_side_payload_carries_no_rule_text (sampled %d)" % attempts, reason)
        report.pending("l3.fold_and_restore_preserve_fact_validity_v2", reason)
    else:
        recorder.install()
        if not recorder.available:
            status["reason"] = "the model-call recorder could not be installed: %s" % (
                "; ".join(recorder.install_errors) or "unknown"
            )
            report.pending("l3.pre_learning_control_does_not_follow_the_rule", status["reason"])
            report.pending("l3.correction_produces_a_rule", status["reason"])
            report.pending("deterministic.rule_text_covers_the_correction", status["reason"])
            report.pending("deterministic.rule_enters_a_new_session_prompt", status["reason"])
            report.pending("l3.correction_does_not_duplicate_the_rule_into_the_memory_store", status["reason"])
            report.pending("l3.a_new_session_follows_the_learned_rule", status["reason"])
            report.pending("l3.denied_confirmation_writes_nothing", status["reason"])
            report.pending("deterministic.disabled_rule_leaves_the_prompt", status["reason"])
            report.pending("l3.correction_migrates_only_confirmed_sources", status["reason"])
            report.pending("l3.disabled_rule_stops_changing_behaviour (sampled %d)" % attempts, status["reason"])
            report.pending("l3.disable_side_payload_carries_no_rule_text (sampled %d)" % attempts, status["reason"])
            report.pending("l3.fold_and_restore_preserve_fact_validity_v2", status["reason"])
        else:
            endpoint = gc.probe_endpoint(seeded["api_base"], run.credentials.get("api_key", ""))
            l3_extra["endpoint"] = endpoint
            if not endpoint["ok"]:
                status["reason"] = "endpoint unreachable: %s" % endpoint.get("error")
                report.pending("l3.pre_learning_control_does_not_follow_the_rule", status["reason"])
                report.pending("l3.correction_produces_a_rule", status["reason"])
                report.pending("deterministic.rule_text_covers_the_correction", status["reason"])
                report.pending("deterministic.rule_enters_a_new_session_prompt", status["reason"])
                report.pending("l3.correction_does_not_duplicate_the_rule_into_the_memory_store", status["reason"])
                report.pending("l3.a_new_session_follows_the_learned_rule", status["reason"])
                report.pending("l3.denied_confirmation_writes_nothing", status["reason"])
                report.pending("deterministic.disabled_rule_leaves_the_prompt", status["reason"])
                report.pending("l3.correction_migrates_only_confirmed_sources", status["reason"])
                report.pending("l3.disabled_rule_stops_changing_behaviour (sampled %d)" % attempts, status["reason"])
                report.pending("l3.disable_side_payload_carries_no_rule_text (sampled %d)" % attempts, status["reason"])
                report.pending("l3.fold_and_restore_preserve_fact_validity_v2", status["reason"])
            else:
                status["status"] = "run"
                try:
                    await run_l3_checks(
                        run, report, registry, store, config, paths, recorder, attempts,
                        baseline, l3_extra, seeded_todos, seeded_event,
                    )
                except Exception as exc:
                    # A crash must still leave evidence: the report is written
                    # below either way, with the exception recorded as a failure.
                    status["runner_exception"] = "%s: %s" % (type(exc).__name__, exc)
                    report.check(
                        "l3.runner_completed_without_an_exception",
                        False,
                        detail={
                            "exception": status["runner_exception"],
                            "note": (
                                "the run stopped before every check could be taken; the "
                                "checks above are the ones that did run"
                            ),
                        },
                        reason=status["runner_exception"],
                    )

    raw_path = run.artifacts_dir / "model-calls.jsonl"
    recorder.dump_raw(raw_path)

    pollution = run.pollution_report()
    report.check(
        "isolation.real_data_directory_untouched",
        pollution["clean"],
        detail=pollution,
        reason="" if pollution["clean"] else "the run changed the machine's real data directory",
    )

    skills_now = list_skills()
    l3_summary = {
        **status,
        "requests": len(recorder.calls),
        "recorder_available": recorder.available,
        "recorder_errors": recorder.install_errors,
        "raw_requests": str(raw_path),
    }
    extra = {
        **l3_extra,
        "skills_before": [entry.get("name") for entry in baseline],
        "skills_after": [
            {key: entry.get(key) for key in ("name", "version", "enabled", "path")}
            for entry in skills_now
        ],
        "requests": recorder.report_view(),
        "model_calls": recorder.model_sequence(),
        "database_after": gc.db_view(store),
        "artifacts": {
            "raw_requests": str(raw_path),
            "workspace_fingerprint": str(run.artifacts_dir / "workspace-fingerprint.json"),
        },
    }
    # A run that did not exercise the model must never overwrite the stable
    # "latest L3 evidence" path: an offline check is a different artifact, and
    # losing the real report to it is exactly the evidence loss this toolkit is
    # supposed to prevent. An explicit --json-out still wins.
    report_path = Path(args.json_out) if args.json_out else (
        REPORT_PATH if l3_summary["status"] == "run" else run.artifacts_dir / REPORT_PATH.name
    )
    payload = report.write(report_path, l3=l3_summary, extra=extra)
    counts = payload["summary"]
    print("")
    print("result: %d passed, %d failed, %d inconclusive, %d pending (of %d)" % (
        counts["passed"], counts["failed"], counts["inconclusive"], counts["pending"], counts["total"]))
    print("l3:     %s %s" % (l3_summary["status"], l3_summary.get("reason", "")))
    print("report: " + str(report_path))
    print("raw:    " + str(raw_path))
    return report.exit_code()


def select_rule_facts(rows, terms) -> list[dict]:
    """Memory rows whose text carries the rule's wording.

    An independent selector on purpose: the gate must not need the runtime's own
    overlap judgment to decide which facts are candidates for being a second home
    of the rule. The runtime's judgment is recorded separately in the report.
    """
    wanted = tuple(str(term) for term in terms if str(term))
    out: list[dict] = []
    for row in rows:
        haystack = "%s %s" % (row.get("title") or "", row.get("detail") or "")
        if any(term in haystack for term in wanted):
            out.append(row)
    return out


def same_session_fact_boundary(calls, probes) -> dict:
    """V2: distinguish forbidden current rules from explicitly invalidated history.

    This applies only to the already-used learning session after fold/restore.
    New-session disable checks retain their all-three-channels zero-text rule.
    """
    from mellowday.runtime.memory import (
        FACT_REMINDER_MARKER, SUPERSEDED_FACTS_MARKER, SUPERSEDED_FACTS_RULE,
    )

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    wanted = [str(probe) for probe in probes if str(probe)]
    errors, allowed = [], []
    scanned = 0
    for index, call in enumerate(calls):
        payload = str(call.get("payload_text") or "")
        if not payload:
            continue
        scanned += 1
        try:
            content = json.loads(payload)
        except ValueError:
            content = payload
        for text in strings(content):
            blocks = re.findall(r"<system-reminder>(.*?)</system-reminder>", text, re.S)
            for block in blocks:
                hits = [probe for probe in wanted if probe in block]
                if not hits:
                    continue
                current, separator, obsolete = block.partition(SUPERSEDED_FACTS_MARKER)
                current_hits = [probe for probe in wanted if probe in current]
                if current_hits:
                    errors.append({"request": index, "reason": "rule in current or uncontrolled injected text",
                                   "probes": current_hits})
                controlled = (block.strip().startswith(FACT_REMINDER_MARKER)
                              and bool(separator) and SUPERSEDED_FACTS_RULE in obsolete)
                obsolete_hits = [probe for probe in wanted if probe in obsolete]
                if obsolete_hits and not controlled:
                    errors.append({"request": index, "reason": "old rule lacks standard invalidation marker or prohibition",
                                   "probes": obsolete_hits})
                elif obsolete_hits:
                    allowed.append({"request": index, "probes": obsolete_hits})
            outside = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
            if (FACT_REMINDER_MARKER in outside or SUPERSEDED_FACTS_MARKER in outside) and any(
                probe in outside for probe in wanted
            ):
                errors.append({"request": index, "reason": "fact reminder is not properly delimited"})
    return {"semantics": "same-session-fact-boundary-v2", "ok": bool(scanned) and not errors,
            "requests_scanned": scanned, "errors": errors, "allowed_invalidated_references": allowed,
            "comparison_note": "V2 permits explicitly invalidated old values; do not combine its denominator with the old zero-text gate."}


def seed_migration_scenario(store) -> dict:
    """Seed only the migration gate, after its unchanged pre-learning control."""
    workflow = store.create_record("memories", {
        "title": "旧每日规划工作流程",
        "detail": "规划时先列当天已有的固定日程，然后只安排三个重点任务。",
        "source": "migration-gate-fixture",
    })
    objective = store.create_record("memories", {
        "title": "每日站会的客观时间",
        "detail": "用户每天上午九点半参加每日站会。",
        "source": "migration-gate-fixture",
    })
    message = (
        CORRECTION + "\n请把已保存的旧工作流程记忆 ID " + workflow["id"]
        + " 迁移到这条习惯中，不再把它作为事实召回；确认时列出该 ID 和原文。"
        + "\n相关客观事实 ID " + objective["id"]
        + " 是站会时间，请保留为有效事实，不要迁移或修改。"
    )
    return {"source_memory_ids": [workflow["id"]], "objective_memory_id": objective["id"],
            "message": message}


def assess_confirmed_migration(before, after, events, confirmations) -> dict:
    """Judge explicit, approved migration only; textual similarity grants no authority.

    Confirmation summaries are captured from the approve=True gate turn. Source
    IDs are read only from the proposal's migration section, never inferred from
    matching fact text. Unselected existing facts must keep their current values.
    """
    old = {str(row.get("id")): row for row in before}
    current = {str(row.get("id")): row for row in after}
    accepted = {str(item.get("summary") or "") for item in confirmations}
    applied = {str(event.get("skill") or "") for event in events
               if event.get("type") == "skill_candidate_applied"}
    selected = {}
    errors = []
    for event in events:
        if event.get("type") != "skill_candidate_proposed":
            continue
        summary = str(event.get("summary") or "")
        marker = "同时把以下事实迁移为技能规则"
        section = summary.split(marker, 1)[1] if marker in summary else ""
        ids = re.findall(r"^- ID ([A-Za-z0-9_-]+) \|", section, re.M)
        if not ids:
            continue
        skill = str(event.get("skill") or "")
        if summary not in accepted or skill not in applied:
            errors.append("migration proposal was not confirmed and successfully applied")
            continue
        for record_id in ids:
            source = old.get(record_id) or current.get(record_id)
            if not source:
                errors.append("missing source snapshot: " + record_id)
                continue
            original = str(source.get("detail") or source.get("content") or "")
            if not original or original not in section:
                errors.append("confirmation omitted original source text: " + record_id)
                continue
            selected[record_id] = skill
    for record_id, skill in selected.items():
        row = current.get(record_id) or {}
        meta = row.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        if row.get("status") != "superseded" or meta.get("superseded_by_skill") != skill:
            errors.append("confirmed source did not migrate to its applied skill: " + record_id)
        source = old.get(record_id)
        if source and any(source.get(k) != row.get(k) for k in ("title", "detail")):
            errors.append("source content changed during migration: " + record_id)
    for record_id, source in old.items():
        if record_id not in selected and source.get("status") == "active":
            row = current.get(record_id) or {}
            if any(source.get(k) != row.get(k) for k in ("status", "title", "detail")):
                errors.append("unselected fact changed: " + record_id)
    status = "failed" if errors else ("passed" if selected else "inconclusive")
    return {"status": status, "source_memory_ids": list(selected), "errors": errors,
            "reason": "; ".join(errors) if errors else (
                "" if selected else "no explicit confirmed migration proposal; similarity alone requires no migration"),
            "unselected_facts_checked": len(set(old) - set(selected))}


def evolution_records(paths, limit: int = 8) -> list[dict]:
    """The last provenance records the learning loop wrote (failure evidence)."""
    base = paths.evolution_dir()
    out: list[dict] = []
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.jsonl")):
        try:
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            continue
        for line in lines[-limit:]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            out.append({"file": path.name, "entry": gc.clip(json.dumps(entry, ensure_ascii=False, default=str), 1200)})
    return out[-limit:]


async def run_l3_checks(
    run, report, registry, store, config, paths, recorder, attempts, baseline, extra,
    seeded_todos, seeded_event,
) -> None:
    from mellowday.runtime.skills import disable_skill, list_skills, reset_skill_cache
    from mellowday.runtime.prompt import build_system_prompt

    baseline_names = [str(entry.get("name")) for entry in baseline]

    # ------------------------------------------- 0. pre-learning control
    before_session = run.session_id("before", 0)
    before_fresh = gc.session_freshness(registry, before_session)
    before = await gc.run_turn(registry, before_session, COMPARE_ASK)
    before_verdict = gc.merge_rule_results(before["reply"], [LEARNED_SPEC])
    extra["pre_learning_sample"] = {**gc.session_summary(before), "freshness": before_fresh,
                                    "rule": before_verdict}
    report.check(
        "l3.pre_learning_control_does_not_follow_the_rule",
        bool(before_fresh["fresh"]) and not before_verdict["ok"],
        detail={
            "freshness": before_fresh,
            "sample": gc.session_summary(before),
            "rule_assertions": before_verdict["detail"],
            "note": (
                "the same request must not already satisfy the rule before it is learned; "
                "otherwise the post-learning result proves nothing"
            ),
        },
        reason="" if not before_verdict["ok"] else "the pre-learning reply already satisfied the rule spec",
    )
    pre_control_ok = bool(before_fresh["fresh"]) and not bool(before_verdict["ok"])

    # --------------------------------- 1. denied confirmation writes nothing
    deny_session = run.session_id("deny", 0)
    deny_fresh = gc.session_freshness(registry, deny_session)
    deny_plan = await gc.run_turn(registry, deny_session, PLAN_ASK)
    deny_turn = await gc.run_turn(registry, deny_session, CORRECTION, approve=False)
    deny_events = (deny_plan["learning"] or []) + (deny_turn["learning"] or [])
    deny_confirmations = (deny_plan["confirmations"] or []) + (deny_turn["confirmations"] or [])
    wrote_after_deny = [
        entry for entry in list_skills() if str(entry.get("name")) not in baseline_names
    ]
    denied_visible = any(
        str(event.get("type")) in {"skill_write_denied", "skill_candidate_skipped"}
        and str(event.get("reason") or "") in {"user_denied", "no_confirmer"}
        for event in deny_events
    )
    candidate_proposed = any(
        str(event.get("type")) == "skill_candidate_proposed" for event in deny_events
    )
    extra["denied_confirmation"] = {
        "freshness": deny_fresh,
        "plan_sample": gc.session_summary(deny_plan),
        "correction_sample": gc.session_summary(deny_turn),
        "learning_events": [gc.clip(json.dumps(event, ensure_ascii=False, default=str), 600)
                            for event in deny_events],
        "confirmations": deny_confirmations,
        "skills_written": [entry.get("name") for entry in wrote_after_deny],
    }
    if not candidate_proposed:
        report.inconclusive(
            "l3.denied_confirmation_writes_nothing",
            "no skill candidate was proposed in the deny run, so 'nothing was written' "
            "cannot be attributed to the declined confirmation",
            detail=extra["denied_confirmation"],
        )
    else:
        report.check(
            "l3.denied_confirmation_writes_nothing",
            not wrote_after_deny and (denied_visible or bool(deny_confirmations)),
            detail=extra["denied_confirmation"],
            reason="" if (not wrote_after_deny and (denied_visible or deny_confirmations))
            else "the declined confirmation still produced a skill, or the refusal was invisible",
        )

    # ------------------------------------------------- 2. the correction lands
    learn_session = run.session_id("learn", 0)
    learn_fresh = gc.session_freshness(registry, learn_session)
    plan_turn = await gc.run_turn(registry, learn_session, PLAN_ASK)
    # Everything the correction window writes into the fact store is captured
    # here: the write-time dedup can only be observed if we know which rows the
    # correction itself created.
    migration_scenario = seed_migration_scenario(store)
    extra["migration_scenario"] = migration_scenario
    fact_rows_before_learn = gc.db_rows(store, "memories")
    fact_ids_before = {str(row.get("id") or "") for row in fact_rows_before_learn}
    correction_turn = await gc.run_turn(
        registry, learn_session, migration_scenario["message"], approve=True,
    )
    fact_rows_after = gc.db_rows(store, "memories")
    facts_written_in_window = [
        row for row in fact_rows_after if str(row.get("id") or "") not in fact_ids_before
    ]

    learn_events = (plan_turn["learning"] or []) + (correction_turn["learning"] or [])
    learn_confirmations = (plan_turn["confirmations"] or []) + (correction_turn["confirmations"] or [])
    reset_skill_cache()
    after_skills = list_skills()
    learned = [entry for entry in after_skills if str(entry.get("name")) not in baseline_names]
    learned_names = [str(entry.get("name")) for entry in learned]
    rule_bodies: dict[str, str] = {}
    for entry in learned:
        path = Path(str(entry.get("path") or ""))
        try:
            rule_bodies[str(entry.get("name"))] = path.read_text(encoding="utf-8")
        except OSError:
            rule_bodies[str(entry.get("name"))] = ""
    applied_events = [event for event in learn_events if str(event.get("type")) == "skill_candidate_applied"]
    inside_run_dir = all(
        str(run.data_dir) in str(entry.get("path") or "") for entry in learned
    ) and bool(learned)
    extra["learning"] = {
        "freshness": learn_fresh,
        "plan_sample": gc.session_summary(plan_turn),
        "correction_sample": gc.session_summary(correction_turn),
        "confirmations": learn_confirmations,
        "learning_events": [gc.clip(json.dumps(event, ensure_ascii=False, default=str), 600)
                            for event in learn_events],
        "learned": [
            {key: entry.get(key) for key in ("name", "version", "enabled", "path", "source")}
            for entry in learned
        ],
        "rule_bodies": {name: gc.clip(body, 2000) for name, body in rule_bodies.items()},
        "provenance_records": evolution_records(paths),
        "baseline": baseline_names,
        "after": [entry.get("name") for entry in after_skills],
        "facts_written_in_the_correction_window": [
            {"id": row.get("id"), "label": row.get("title"), "status": row.get("status"),
             "detail": gc.clip(row.get("detail"), 240), "meta": gc.clip(row.get("meta"), 400)}
            for row in facts_written_in_window
        ],
        "superseded_rows": [
            {"id": row.get("id"), "label": row.get("title"), "status": row.get("status"),
             "detail": gc.clip(row.get("detail"), 240), "meta": gc.clip(row.get("meta"), 400)}
            for row in fact_rows_after if str(row.get("status") or "") == "superseded"
        ],
    }
    report.check(
        "l3.correction_produces_a_rule",
        bool(learned) and bool(applied_events) and bool(learn_confirmations) and inside_run_dir,
        detail=extra["learning"],
        reason="" if (learned and applied_events and learn_confirmations and inside_run_dir)
        else "no confirmed, applied skill artifact was produced by the correction",
    )

    migration = assess_confirmed_migration(
        fact_rows_before_learn, fact_rows_after, learn_events, learn_confirmations,
    )
    if migration["status"] == "passed" and set(migration["source_memory_ids"]) != set(migration_scenario["source_memory_ids"]):
        migration["status"] = "failed"
        migration["reason"] = "the confirmed migration did not select exactly the explicitly requested workflow ID"
        migration["errors"].append(migration["reason"])
    extra["supersession"] = migration
    if migration["status"] == "inconclusive":
        report.inconclusive("l3.correction_migrates_only_confirmed_sources",
                            migration["reason"], detail=migration)
    else:
        report.check("l3.correction_migrates_only_confirmed_sources",
                     migration["status"] == "passed", detail=migration,
                     reason=migration["reason"])

    if not learned:
        reason = "no rule was learned in this run"
        for name in (
            "deterministic.rule_text_covers_the_correction",
            "deterministic.rule_enters_a_new_session_prompt",
            "l3.correction_does_not_duplicate_the_rule_into_the_memory_store",
            "l3.a_new_session_follows_the_learned_rule",
            "deterministic.disabled_rule_leaves_the_prompt",
            "l3.disabled_rule_stops_changing_behaviour (sampled %d)" % attempts,
            "l3.disable_side_payload_carries_no_rule_text (sampled %d)" % attempts,
            "l3.fold_and_restore_preserve_fact_validity_v2",
        ):
            report.inconclusive(name, reason, detail=extra["learning"])
        return

    # --------------------------------------- 3. the artifact really encodes it
    covers = {
        name: {term: term in body for term in RULE_TERMS}
        for name, body in rule_bodies.items()
    }
    covers_ok = any(all(flags.values()) for flags in covers.values())
    report.check(
        "deterministic.rule_text_covers_the_correction",
        covers_ok,
        detail={
            "requirement_terms": list(RULE_TERMS),
            "per_skill": covers,
            "rule_bodies": {name: gc.clip(body, 1200) for name, body in rule_bodies.items()},
        },
        reason="" if covers_ok else "the stored rule does not mention both requirements of the correction",
    )

    # ------------------------------------ 4. it enters a brand new session prompt
    # The base prompt carries the skill's name and description; the rule *body*
    # is delivered per request through the skill tool. Both halves are checked,
    # the second one by the outbound payload probe in section 5.
    reset_skill_cache()
    prompt_after = build_system_prompt()
    descriptions = {
        str(entry.get("name")): str(entry.get("description") or "") for entry in learned
    }
    prompt_hits = {name: name in prompt_after for name in learned_names}
    description_hits = {
        name: bool(descriptions[name]) and descriptions[name] in prompt_after
        for name in learned_names
    }
    extra["prompt_after_learning"] = {
        "chars": len(prompt_after),
        "skill_names_present": prompt_hits,
        "skill_descriptions_present": description_hits,
        "descriptions": descriptions,
        "excerpt": gc.clip(prompt_after[-1500:], 1500),
        "delivery_note": (
            "the rule body reaches the model through the skill tool call, which the "
            "per-request payload probe below verifies"
        ),
    }
    report.check(
        "deterministic.rule_enters_a_new_session_prompt",
        all(prompt_hits.values()) and all(description_hits.values()),
        detail=extra["prompt_after_learning"],
    )

    # --------------- 4b. the same correction must not silently become a fact
    # The runtime injects recalled facts into every session regardless of any
    # skill's enabled state, so a duplicate write there would make "disable the
    # habit" meaningless. This is checked on the store, not on the reply.
    active_facts = gc.db_rows(store, "memories", include_done=False)
    duplicating_rows = []
    for row in active_facts:
        haystack = "%s %s" % (row.get("title") or "", row.get("detail") or "")
        terms = [term for term in RULE_TERMS if term in haystack]
        if terms:
            duplicating_rows.append(
                {
                    "id": row.get("id"),
                    "label": row.get("title"),
                    "content": gc.clip(row.get("detail"), 300),
                    "status": row.get("status"),
                    "rule_terms": terms,
                }
            )
    extra["memory_after_learning"] = {
        "active_facts": len(active_facts),
        "facts_carrying_the_rule": duplicating_rows,
        "note": (
            "the fact store is a second delivery channel for the same instruction; "
            "it is injected into every new session, so the disabled-skill side must "
            "be judged with it in view"
        ),
    }
    report.check(
        "l3.correction_does_not_duplicate_the_rule_into_the_memory_store",
        not migration["errors"],
        detail={"migration": migration, "text_matches_for_payload_followup": duplicating_rows,
                "note": "Text overlap alone does not establish a duplicate instruction; "
                        "unselected objective facts must survive. Disable-side payload checks "
                        "below independently fail on actual rule leakage."},
        reason=migration["reason"] if migration["errors"] else "",
    )

    def restore_business_baseline() -> dict[str, Any]:
        """Delete rows the comparison turns wrote, so the conditions match.

        The memory store is deliberately left untouched: a duplicate write there
        is itself under test (see the check above). The seeded calendar entry and
        the seeded to-dos are kept, so 'before', 'after' and 'disabled' all run
        against the same records.
        """
        keep = set(str(value) for value in seeded_todos.values())
        keep.add(str(seeded_event.get("id") or ""))
        removed: list[str] = []
        for kind in ("todos", "calendar", "reminders", "notes"):
            for row in gc.db_rows(store, kind):
                record_id = str(row.get("id") or "")
                if not record_id or record_id in keep:
                    continue
                try:
                    store.delete_record(kind, record_id)
                except Exception:
                    continue
                removed.append("%s:%s" % (kind, row.get("title")))
        return {
            "removed": removed,
            "todos_left": [row.get("title") for row in gc.db_rows(store, "todos")],
        }

    # --------------------------------------------- 5. behaviour in new sessions
    probes = [*learned_names, *RULE_TERMS]
    baseline_before_after = restore_business_baseline()
    after_samples = await gc.sample_sessions(
        registry, run, "after", COMPARE_ASK, attempts, specs=[LEARNED_SPEC],
        recorder=recorder, payload_probes=probes,
    )
    for sample in after_samples:
        seqs = set(int(value) for value in (sample.get("request_seqs") or []))
        calls = [call for call in recorder.calls if int(call["seq"]) in seqs]
        sample["channels"] = gc.payload_channel_evidence(calls, probes)
    extra["after_learning_samples"] = after_samples
    extra["baseline_before_after"] = baseline_before_after
    hits = sum(1 for sample in after_samples if sample.get("hit"))
    valid = sum(1 for sample in after_samples if sample.get("valid"))
    delivered = sum(1 for sample in after_samples if sample.get("payload_probe_present"))
    real_record_in_every_valid = all(
        bool((sample.get("rule") or {}).get("detail", {}).get("assertions", {}).get(
            "term:" + SEED_EVENT_TITLE, False))
        for sample in after_samples
        if sample.get("valid")
    )
    ok_after, detail_after = gc.on_side_verdict(after_samples, min_hits=1)
    ok_after = (
        ok_after
        and real_record_in_every_valid
        and pre_control_ok
        and valid == len(after_samples)
        and delivered == len(after_samples)
    )
    report.check(
        "l3.a_new_session_follows_the_learned_rule (sampled %d)" % attempts,
        ok_after,
        detail={
            "verdict": detail_after,
            "samples_ref": "after_learning_samples",
            "pre_learning_control_ok": pre_control_ok,
            "real_fixed_schedule_in_every_valid_sample": real_record_in_every_valid,
            "all_samples_answered": valid == len(after_samples),
            "rule_text_delivered_in_every_request": delivered == len(after_samples),
            "samples": after_samples,
        },
        metrics={"hits": hits, "of": len(after_samples), "valid": valid, "delivered": delivered},
        reason="" if ok_after else (
            detail_after.get("inconclusive_reason")
            or "at least one sample did not follow the learned rule"
        ),
    )

    # ------------------------------------------------------- 6. disabling it
    disabled = disable_skill(learned_names[0])
    reset_skill_cache()
    prompt_disabled = build_system_prompt()
    prompt_gone = all(name not in prompt_disabled for name in learned_names)
    report.check(
        "deterministic.disabled_rule_leaves_the_prompt",
        bool(disabled.get("ok")) and prompt_gone,
        detail={
            "disable_result": {key: disabled.get(key) for key in ("ok", "changed", "archived_to")},
            "skill_names_absent": prompt_gone,
            "chars_before": len(prompt_after),
            "chars_after": len(prompt_disabled),
        },
    )

    baseline_before_off = restore_business_baseline()
    off_samples = await gc.sample_sessions(
        registry, run, "off", COMPARE_ASK, attempts, specs=[LEARNED_SPEC],
        recorder=recorder, payload_probes=probes,
    )
    probe_set = [probe for probe in list(probes) + list(RULE_TERMS) if probe]
    for sample in off_samples:
        seqs = set(int(value) for value in (sample.get("request_seqs") or []))
        calls = [call for call in recorder.calls if int(call["seq"]) in seqs]
        sample["channels"] = gc.payload_channel_evidence(
            calls, probes, fact_probes=list(RULE_TERMS)
        )
        sample["probe_locations"] = gc.payload_probe_locations(calls, probe_set)
    extra["off_after_disable_samples"] = off_samples
    # The disable-side claim is about the *request payload*, not about the skill
    # list or the system prompt: the rule text must be absent from the
    # recalled-facts block, from the superseded-values block and from the rest of
    # the request, in every sample.
    carriers = [
        sample for sample in off_samples
        if (sample.get("probe_locations") or {}).get("present_anywhere")
    ]
    report.check(
        "l3.disable_side_payload_carries_no_rule_text (sampled %d)" % attempts,
        not carriers and all(
            (sample.get("probe_locations") or {}).get("requests_scanned") for sample in off_samples
        ),
        detail={
            "probes": probe_set,
            "samples_with_rule_text": [
                {
                    "session_id": sample.get("session_id"),
                    "locations": sample.get("probe_locations"),
                }
                for sample in carriers
            ],
            "per_sample_locations": [
                {"session_id": sample.get("session_id"),
                 "locations": sample.get("probe_locations")}
                for sample in off_samples
            ],
            "note": (
                "covers the injected recalled-facts block, the injected superseded-values "
                "block and the rest of the request"
            ),
        },
        metrics={"samples_carrying_rule_text": len(carriers), "of": len(off_samples)},
        reason="" if not carriers else (
            "the disabled rule still reached the model through the request payload"
        ),
    )
    extra["baseline_before_off"] = baseline_before_off
    control_ok = bool(ok_after) and hits >= 1
    ok_off, detail_off = gc.off_side_verdict(off_samples, control_ok=control_ok)
    fact_carriers = [
        sample for sample in off_samples
        if (sample.get("channels") or {}).get("via_recalled_facts")
    ]
    skill_carriers = [
        sample for sample in off_samples
        if (sample.get("channels") or {}).get("via_skill_or_conversation")
    ]
    reason = detail_off.get("inconclusive_reason", "") or detail_off.get("reason", "")
    if not ok_off and skill_carriers:
        reason = (
            "the disabled skill text was still delivered to the model in %d of %d requests"
            % (len(skill_carriers), len(off_samples))
        )
    elif not ok_off and fact_carriers:
        reason = (
            "disabling the skill did not stop the behaviour: the rule text still reached "
            "the model through the user-fact store in %d of %d requests (%s)"
            % (
                len(fact_carriers),
                len(off_samples),
                "; ".join(
                    str((sample.get("channels") or {}).get("via_recalled_facts"))
                    for sample in fact_carriers
                ),
            )
        )
    elif not ok_off and not skill_carriers and not fact_carriers:
        reason = (
            "the samples still satisfied the rule although neither channel carried its "
            "text, so this rule spec does not discriminate on this question"
        )
    # ------------------------------------------------ 7. fold, then restore
    # The rule text is present in the learning session's own history (the model
    # asked for the skill and read its body). Folding must not put it into the
    # folded memory, and restoring the session in a fresh store/registry must not
    # put it back into the injected blocks - including the superseded-values
    # paragraph, which is the specific way a "removed" rule used to reappear.
    learn_agent = registry.get(learn_session).agent
    messages_before = len(getattr(learn_agent, "_openai_messages", []) or [])
    fold_error = ""
    try:
        await learn_agent.compact()
    except Exception as exc:
        fold_error = "%s: %s" % (type(exc).__name__, exc)
    messages_after = len(getattr(learn_agent, "_openai_messages", []) or [])
    folded_memories = list(getattr(learn_agent, "_folded_session_memories", []) or [])
    folded_text = json.dumps(folded_memories, ensure_ascii=False, default=str)
    folded_terms = [term for term in list(probes) + list(RULE_TERMS) if term and term in folded_text]
    seq_before_fold_turn = len(recorder.calls)
    fold_turn = await gc.run_turn(registry, learn_session, PLAN_ASK)
    fold_calls = list(recorder.calls[seq_before_fold_turn:])
    fold_locations = gc.payload_probe_locations(fold_calls, probe_set)
    fold_boundary = same_session_fact_boundary(fold_calls, probe_set)
    # Restore in a brand new store/registry: the same path a process restart takes
    # (build_agent -> load_session) without needing a second interpreter.
    from mellowday.runtime import sessions as session_store
    from mellowday.storage.store import Store as _Store
    from mellowday.web_app.service import SessionRegistry as _Registry

    restored_store = _Store(data_dir=run.data_dir)
    restored_registry = _Registry(store=restored_store)
    seq_before_restore = len(recorder.calls)
    restore_turn = await gc.run_turn(restored_registry, learn_session, COMPARE_ASK)
    restore_calls = recorder.calls[seq_before_restore:]
    restore_locations = gc.payload_probe_locations(restore_calls, probe_set)
    restore_boundary = same_session_fact_boundary(restore_calls, probe_set)
    saved = session_store.load_session(learn_session) or {}
    restored_messages = saved.get("openaiMessages") if isinstance(saved.get("openaiMessages"), list) else []
    extra["fold_and_restore"] = {
        "session_id": learn_session,
        "messages_before_fold": messages_before,
        "messages_after_fold": messages_after,
        "folded_memories": len(folded_memories),
        "folded_text": gc.clip(folded_text, 2000),
        # Recorded, not asserted: the conversation itself was *about* the rule
        # (the user corrected the assistant), so a summary that mentions its
        # wording is not a leak. V2 rejects current rule facts and permits old
        # values only in a standard explicitly invalidated reminder section.
        "rule_terms_in_folded_memory": folded_terms,
        "fold_error": fold_error,
        "fold_turn": gc.session_summary(fold_turn),
        "continue_after_fold_probe_locations": fold_locations,
        "restore_turn": gc.session_summary(restore_turn),
        "restored_message_count": len(restored_messages),
        "restore_probe_locations": restore_locations,
        "same_session_semantics": "same-session-fact-boundary-v2",
        "fold_boundary": fold_boundary,
        "restore_boundary": restore_boundary,
        "comparison_note": "V2 is not comparable with the old zero-text check; do not pool denominators.",
    }
    injected_clean_after_fold = fold_boundary["ok"]
    injected_clean_after_restore = restore_boundary["ok"]
    ok_fold = (
        not fold_error
        and messages_after < messages_before
        and bool(folded_memories)
        and bool((fold_locations or {}).get("requests_scanned"))
        and injected_clean_after_fold
        and bool((restore_locations or {}).get("requests_scanned"))
        and injected_clean_after_restore
        and len(restored_messages) > 0
        # "elsewhere in the request" is deliberately *not* asserted here: this
        # session's own conversation is about the rule (the user corrected the
        # assistant), so its history mentioning the wording is not a leak. Only
        # current facts must stay clean; old references need controlled invalidation.
    )
    report.check(
        "l3.fold_and_restore_preserve_fact_validity_v2",
        ok_fold,
        detail=extra["fold_and_restore"],
        metrics={
            "messages_before": messages_before,
            "messages_after": messages_after,
            "folded_rule_terms": len(folded_terms),
            "restored_messages": len(restored_messages),
            "rule_text_in_restored_injected_blocks": len(
                (restore_locations.get("in_recalled_facts_block") or [])
                + (restore_locations.get("in_superseded_block") or [])
            ),
            "rule_text_in_continue_after_fold_injected_blocks": len(
                (fold_locations.get("in_recalled_facts_block") or [])
                + (fold_locations.get("in_superseded_block") or [])
            ),
            "rule_terms_in_folded_summary_recorded_only": len(folded_terms),
        },
        reason="" if ok_fold else (
            fold_error or "the rule returned as current fact or lacked explicit invalidation after fold/restore"
        ),
    )

    report.check(
        "l3.disabled_rule_stops_changing_behaviour (sampled %d)" % attempts,
        ok_off,
        detail={
            "verdict": detail_off,
            "samples_ref": "off_after_disable_samples",
            "control_from_enabled_samples": {"hits": hits, "of": len(after_samples)},
            "samples_still_carried_by_skill": len(skill_carriers),
            "samples_still_carried_by_recalled_facts": len(fact_carriers),
            "samples": off_samples,
        },
        metrics={"hits": detail_off["hits"], "of": detail_off["of"], "valid": detail_off["valid"]},
        reason=reason,
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
