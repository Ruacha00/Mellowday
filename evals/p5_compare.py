"""Minimal P5 comparison: skill off / fixed skill / learned skill.

The comparison this script records is deliberately small and deliberately
narrow. It measures one thing - whether a fresh session, asked to plan a day,
follows the output rule and reads the records that actually exist - under three
conditions that differ only in how the rule got there:

  off      no planning skill at all (the control);
  fixed    a hand-written planning skill with the same requirements;
  learned  the rule a real correction produced through the product path.

Both cases use the same model configuration and the same business seed:

  dev      tomorrow's records - the request the correction was made about;
  holdout  next Monday's records - a different day, different records, never
           part of the correction and seeded only after the learning turn.

The holdout records are seeded after the learning turn on purpose: what is
being tested is whether the rule generalises, not whether the model can copy
the example it was trained on.

The script reports counts with their denominators and a verbatim failure list.
It does not compute, print or claim an improvement ratio, and a small sample is
reported as a small sample.

    python scripts/../evals/p5_compare.py --samples 3
    python evals/p5_compare.py --offline

Exit codes: 0 measurement integrity held, 1 an integrity check failed,
2 the model-driven part was not run (no credentials or --offline).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import gate_common as gc  # noqa: E402
from demo_core import (  # noqa: E402  (shared, runtime-derived helpers)
    evaluate_structural_rule,
    pick_body_probe,
    retrieval_block,
    rule_delivery,
)

GATE = "p5-comparison"
REPORT_PATH = REPO / "docs" / "evidence" / "raw" / "p5-comparison-report.json"

CONDITIONS = ("off", "fixed", "learned")
CASES = ("dev", "holdout")

DEV_EVENT = "每日站会"
DEV_TODOS = ("写季度报告", "开项目周会", "买生日礼物", "整理收件箱", "续保车险", "预约体检")
DEV_ASK = "帮我规划一下明天要做的事。"

HOLD_EVENT = "客户复盘会"
HOLD_TODOS = ("准备演示材料", "更新报价单", "跟进合同", "提交周报")
HOLD_ASK = "帮我规划一下下周一的安排。"

FACTS = (
    ("用户通常六点（18:00）下班。", "下班时间", "preference"),
    ("用户偏好上午处理需要专注的工作（深度工作），下午安排会议。", "工作节奏", "preference"),
)

CORRECTION = "不对。以后帮我规划的时候，必须先列出当天已有的固定日程，然后只排三个重点任务，不要一次列十几条。"

FIXED_SKILL_NAME = "固定规划格式"
FIXED_SKILL_DESC = "规划某一天的事务时的固定输出格式"
FIXED_SKILL_BODY = (
    "# 步骤\n\n"
    "规划任何一天的事务时：\n"
    "1. 先给出「固定日程」小节，列出当天已有的日程与截止当天的待办。\n"
    "2. 再给出「重点任务」小节，只排三个重点任务。\n"
    "3. 不要一次列出十几条。\n"
)

RULE_TEXT_PROBES = ("固定日程", "重点任务")
"""Phrases any version of the planning rule carries.

Used to assert from the *request payload* that a condition really has no rule
text: both the injected recalled-facts block and the injected superseded-values
block are scanned, plus the rest of the request.
"""


FIXED_BODY_PROBE = "不要一次列出十几条"
"""A phrase that exists only in the hand-written skill body, never in its description."""


CASE_META = {
    "dev": {"event": DEV_EVENT, "todos": list(DEV_TODOS), "ask": DEV_ASK},
    "holdout": {"event": HOLD_EVENT, "todos": list(HOLD_TODOS), "ask": HOLD_ASK},
}
"""What each case seeds; the assertions are derived from these records.

No section titles are asserted: a reply that leads with the real fixed schedule,
commits to exactly three priority tasks drawn from the real to-dos and never
dumps a long list satisfies the rule whatever it calls its headings (T6 F2).
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=3, help="samples per case per condition (default 3)")
    parser.add_argument("--run-root", default=str(gc.DEFAULT_RUN_ROOT))
    parser.add_argument("--run-prefix", default="", help="shared suffix for the three run ids")
    parser.add_argument("--json-out", default=str(REPORT_PATH))
    parser.add_argument("--source-data-dir", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--only", default="", help="run one condition only (off|fixed|learned)")
    parser.add_argument("--arm-json", default="",
                        help="write this process's arm result here (one arm per process)")
    parser.add_argument("--no-isolate-arms", dest="isolate_arms", action="store_false", default=True,
                        help="run all arms inside one process (debugging only: the skills cache is global)")
    parser.add_argument("--arm-log-dir", default="", help="where per-arm subprocess logs are written")
    parser.add_argument("--no-keep-run-dir", dest="keep", action="store_false", default=True)
    return parser.parse_args()


def tomorrow_local_iso(hour: int, minute: int) -> str:
    now = datetime.now().astimezone()
    target = datetime.combine((now + timedelta(days=1)).date(), clock_time(hour, minute))
    return target.replace(tzinfo=now.tzinfo).isoformat()


def next_monday_local_iso(hour: int, minute: int) -> str:
    now = datetime.now().astimezone()
    days_ahead = (7 - now.weekday()) or 7
    target = datetime.combine((now + timedelta(days=days_ahead)).date(), clock_time(hour, minute))
    return target.replace(tzinfo=now.tzinfo).isoformat()


async def seed_business(store, *, holdout: bool) -> dict:
    """Write one case's records; both cases share the same shape."""
    if holdout:
        event_title, todos, due = HOLD_EVENT, HOLD_TODOS, next_monday_local_iso(14, 0)
        todo_due = next_monday_local_iso(0, 0)
    else:
        event_title, todos, due = DEV_EVENT, DEV_TODOS, tomorrow_local_iso(9, 30)
        todo_due = tomorrow_local_iso(0, 0)
    event = await gc.call_tool(
        store, "create_calendar_event",
        {"title": event_title, "due_at": due, "status": "scheduled", "detail": "演示用日程"},
    )
    ids = {}
    for title in todos:
        created = await gc.call_tool(
            store, "create_todo", {"title": title, "due_at": todo_due, "status": "open"}
        )
        ids[title] = str(created.get("id") or "")
    return {"event": event_title, "event_ok": event.get("ok"), "event_due_local": event.get("due_at_local"),
            "todos": list(todos), "todo_ids": ids}


async def measure_case(registry, run, recorder, condition: str, case: str, samples: int,
                       probes: list[str], *, rule_name: str, body_probe: str) -> dict:
    meta = CASE_META[case]
    ask = str(meta["ask"])
    rows = []
    for index in range(samples):
        session_id = run.session_id("%s-%s" % (condition, case), index)
        freshness = gc.session_freshness(registry, session_id)
        seq_before = len(recorder.calls)
        result = await gc.run_turn(registry, session_id, ask)
        calls = recorder.calls[seq_before:]
        summary = gc.session_summary(result)
        verdict = evaluate_structural_rule(
            result.get("reply"), event_title=str(meta["event"]), todos=list(meta["todos"])
        )
        delivery = rule_delivery(calls, rule_name=rule_name, body_probe=body_probe)
        probe_locations = gc.payload_probe_locations(
            calls, [probe for probe in (*RULE_TEXT_PROBES, body_probe) if probe]
        )
        loaded = bool(
            delivery["retrieved_block_mentions_rule"]
            or delivery["body_probe_in_payload"]
            or any(tool.get("name") == "skill" for tool in summary.get("tool_calls") or [])
        )
        summary.update({
            "freshness": freshness,
            "hit": bool(verdict["ok"]),
            "rule": verdict,
            "rule_loaded": loaded,
            "delivery": delivery,
            "probe_locations": probe_locations,
            "channels": gc.payload_channel_evidence(
                calls, probes, fact_probes=[str(meta["event"])]
            ),
            "models_sent": sorted({str(call.get("model") or "") for call in calls}),
        })
        rows.append(summary)
    hits = sum(1 for row in rows if row.get("hit"))
    valid = sum(1 for row in rows if row.get("valid"))
    loaded = sum(1 for row in rows if row.get("rule_loaded"))
    carrying = [row for row in rows if (row.get("probe_locations") or {}).get("present_anywhere")]
    return {
        "condition": condition,
        "case": case,
        "ask": ask,
        "case_meta": {"event": meta["event"], "todos": list(meta["todos"]), "ask": ask},
        "samples": rows,
        "hits": hits,
        "valid": valid,
        "of": len(rows),
        "rule_loaded": loaded,
        "samples_carrying_rule_text": len(carrying),
        "adherence": ("%d/%d" % (hits, valid)) if valid else "n/a",
        "rule_loaded_ratio": ("%d/%d" % (loaded, valid)) if valid else "n/a",
    }


def arm_comparability(results: list[dict]) -> dict:
    """Require a common, recorded code snapshot and model config across arms."""
    fingerprints = [result.get("fingerprint") for result in results]
    models = [json.dumps(result.get("model_config"), ensure_ascii=False, sort_keys=True)
              for result in results]
    same_model = bool(results) and len(set(models)) == 1
    same_workspace = bool(fingerprints) and all(isinstance(value, str) and value for value in fingerprints)
    same_workspace = bool(same_workspace and len(set(fingerprints)) == 1)
    return {"same_model_configuration": same_model,
            "same_workspace_fingerprint": same_workspace,
            "workspace_fingerprints": fingerprints,
            "passed": same_model and same_workspace}


async def run_condition(args: argparse.Namespace, condition: str, samples: int) -> dict:
    run = gc.RunContext(
        "%s-%s" % (GATE, condition),
        run_root=args.run_root,
        run_id=("%s-%s" % (args.run_prefix, condition)) if args.run_prefix else "",
        keep=args.keep,
        source_data_dir=args.source_data_dir or None,
    ).prepare()
    report = gc.Report("%s-%s" % (GATE, condition), run)
    gc.ensure_src_on_path()
    seeded = run.seed_model_config()

    from mellowday.runtime.prompt import build_system_prompt
    from mellowday.runtime.skills import create_skill_file, list_skills, reset_skill_cache
    from mellowday.storage.store import Store
    from mellowday.web_app.service import SessionRegistry

    # The skills package caches its discovery result in a process-global. Each
    # arm has its own data directory, so the cache has to be dropped when the
    # directory changes - otherwise the previous arm's skill is what this arm
    # sees (and merges into).
    reset_skill_cache()
    store = Store(data_dir=run.data_dir)
    registry = SessionRegistry(store=store)
    recorder = gc.ModelCallRecorder()
    recorder.install()

    offline = bool(args.offline or not seeded["api_key_present"])
    offline_reason = "offline mode requested" if args.offline else (
        "" if seeded["api_key_present"] else "no credential available"
    )
    detail: dict = {
        "condition": condition,
        "run_id": run.run_id,
        "data_dir": str(run.data_dir),
        "model_config": seeded,
        "samples_requested": samples,
    }

    dev_seed = await seed_business(store, holdout=False)
    facts = []
    for content, label, kind in FACTS:
        stored = await gc.call_tool(
            store, "remember_fact", {"content": content, "label": label, "kind": kind}
        )
        facts.append({"label": label, "ok": stored.get("ok")})
    detail["seed_dev"] = dev_seed
    detail["facts"] = facts

    rule_name = ""
    body_probe = ""
    rule_probes: list[str] = []
    learned_detail: dict = {}
    migration = None
    if condition == "fixed":
        created = create_skill_file(
            name=FIXED_SKILL_NAME, description=FIXED_SKILL_DESC, instructions=FIXED_SKILL_BODY
        )
        reset_skill_cache()
        learned_detail = {"created": {key: created.get(key) for key in ("ok", "name", "version", "file")}}
        rule_name = FIXED_SKILL_NAME
        body_probe = FIXED_BODY_PROBE
        rule_probes = [FIXED_SKILL_NAME, FIXED_BODY_PROBE]
    elif condition == "learned" and offline:
        # Without a model there is no correction to learn from, and --offline
        # must not send a single request; the arm is reported as not set up.
        learned_detail = {"skipped": offline_reason or "offline"}
    elif condition == "learned":
        plan = await gc.run_turn(registry, run.session_id("learn", 0), DEV_ASK)
        facts_before_correction = gc.db_rows(store, "memories")
        correction = await gc.run_turn(
            registry, run.session_id("learn", 0), CORRECTION, approve=True
        )
        from gate_l3_learning import assess_confirmed_migration
        migration = assess_confirmed_migration(
            facts_before_correction, gc.db_rows(store, "memories"),
            correction.get("learning") or [], correction.get("confirmations") or [],
        )
        if migration["status"] == "inconclusive":
            detail["optional_migration_evidence"] = {
                **migration, "status": "pending", "required_for_this_comparison": False,
                "reason": "The comparison keeps its original correction; explicit migration is tested by the learning gate.",
            }
        else:
            report.check("p5.confirmed_source_memories_migrate", migration["status"] == "passed",
                         detail=migration, reason=migration["reason"])
        reset_skill_cache()
        learned = [entry for entry in list_skills()]
        if learned:
            rule_name = str(learned[0].get("name") or "")
            try:
                body = Path(str(learned[0].get("path") or "")).read_text(encoding="utf-8")
            except OSError:
                body = ""
            body_probe = pick_body_probe(body, str(learned[0].get("description") or ""))
        learned_detail = {
            "plan": gc.session_summary(plan),
            "correction": gc.session_summary(correction),
            "skills": [{key: entry.get(key) for key in ("name", "version", "enabled", "path")}
                       for entry in learned],
            "body_probe": body_probe,
        }
        rule_probes = [probe for probe in (rule_name, body_probe) if probe]

    # The holdout records are only written now: after the learning turn, so the
    # learned arm never saw them, and at the same point for every condition.
    hold_seed = await seed_business(store, holdout=True)
    detail["seed_holdout"] = hold_seed
    detail["rule_probes"] = rule_probes
    detail["rule_name"] = rule_name
    detail["body_probe"] = body_probe

    checklist: dict[str, dict] = {}
    if offline:
        for case in CASES:
            checklist[case] = {"condition": condition, "case": case, "hits": 0, "valid": 0,
                               "of": samples, "adherence": "n/a", "samples": [],
                               "pending": "offline mode requested" if args.offline else "no credential"}
    else:
        for case in CASES:
            checklist[case] = await measure_case(
                registry, run, recorder, condition, case, samples, rule_probes,
                rule_name=rule_name, body_probe=body_probe,
            )

    prompt = build_system_prompt()
    detail["measurements"] = checklist
    detail["prompt_has_rule"] = {probe: (probe in prompt) for probe in rule_probes}
    entries_now = list_skills()
    rule_facts = [
        {"label": row.get("title"), "content": gc.clip(row.get("detail"), 200)}
        for row in gc.db_rows(store, "memories", include_done=False)
        if any(term in str(row.get("detail") or "") for term in ("固定日程", "重点任务"))
    ]
    if condition == "off":
        rule_state_ok = not entries_now and not rule_facts
    else:
        rule_state_ok = (
            any(str(entry.get("name")) == rule_name and entry.get("enabled") for entry in entries_now)
            and bool(body_probe)
        )
    superseded_rule_facts = [
        {"label": row.get("title"), "status": row.get("status"),
         "meta": gc.clip(row.get("meta"), 300), "content": gc.clip(row.get("detail"), 200)}
        for row in gc.db_rows(store, "memories")
        if str(row.get("status") or "") == "superseded"
        and any(term in str(row.get("detail") or "") for term in ("固定日程", "重点任务"))
    ]
    detail["rule_state"] = {
        "condition": condition,
        "skills": [{"name": entry.get("name"), "enabled": entry.get("enabled"),
                    "version": entry.get("version")} for entry in entries_now],
        "rule_name": rule_name,
        "body_probe": body_probe,
        "body_probe_in_prompt": bool(body_probe) and body_probe in prompt,
        "facts_carrying_the_rule": rule_facts,
        "superseded_rule_facts": superseded_rule_facts,
        "note": (
            "the off arm must have no rule anywhere; the fixed and learned arms must have an "
            "enabled skill whose body is in the prompt. A rule fact may additionally exist in "
            "the learned arm pre-t9; it is recorded, not hidden."
        ),
    }
    detail["endpoint_models"] = (
        gc.probe_endpoint(seeded["api_base"], run.credentials.get("api_key", "")).get("models")
        if not offline else []
    )

    raw_path = run.artifacts_dir / "model-calls.jsonl"
    recorder.dump_raw(raw_path)
    pollution = run.pollution_report()
    report.check(
        "isolation.real_data_directory_untouched",
        pollution["clean"],
        detail=pollution,
    )
    if condition == "learned" and offline:
        report.pending(
            "p5.condition_rule_state_is_as_intended",
            "the learned arm needs a real correction turn: %s" % (offline_reason or "offline"),
            detail=detail["rule_state"],
        )
    else:
        report.check(
            "p5.condition_rule_state_is_as_intended",
            rule_state_ok,
            detail=detail["rule_state"],
            reason="" if rule_state_ok else "the arm's rule state is not what this condition requires",
        )
    # Migration authority comes from the confirmed source IDs, not text overlap.
    # Keep text matches as diagnostics; delivery-channel checks below still fail
    # when the outbound payload actually carries the rule through facts.
    if offline:
        report.pending(
            "p5.%s_rule_is_not_active_in_the_fact_store" % condition,
            "offline mode requested" if args.offline else "no credential available",
            detail=detail["rule_state"],
        )
    else:
        report.check(
            "p5.%s_rule_is_not_active_in_the_fact_store" % condition,
            not (migration and migration["errors"]),
            detail={
                "confirmed_migration": migration,
                "active_facts_carrying_the_rule": rule_facts,
                "superseded_rule_facts": superseded_rule_facts,
                "note": (
                    "Text matches are diagnostic, not authorization to migrate facts. Only explicit "
                    "confirmed source IDs may migrate; payload channel checks remain authoritative."
                ),
            },
            metrics={"active_rule_facts": len(rule_facts),
                     "superseded_rule_facts": len(superseded_rule_facts)},
            reason=migration["reason"] if migration and migration["errors"] else "",
        )
    per_channel = {
        case: {
            "skill_only": sum(1 for row in checklist[case]["samples"]
                              if (row.get("channels") or {}).get("via_skill_or_conversation")
                              and not (row.get("channels") or {}).get("via_recalled_facts")),
            "facts_only": sum(1 for row in checklist[case]["samples"]
                              if (row.get("channels") or {}).get("via_recalled_facts")
                              and not (row.get("channels") or {}).get("via_skill_or_conversation")),
            "both_channels": sum(1 for row in checklist[case]["samples"]
                                 if (row.get("channels") or {}).get("via_recalled_facts")
                                 and (row.get("channels") or {}).get("via_skill_or_conversation")),
            "neither": sum(1 for row in checklist[case]["samples"]
                           if not (row.get("channels") or {}).get("via_recalled_facts")
                           and not (row.get("channels") or {}).get("via_skill_or_conversation")),
            "of": checklist[case]["of"],
        }
        for case in CASES
    }
    detail["delivery_channels"] = per_channel
    report.check(
        "p5.%s_delivery_channels_recorded" % condition,
        all(value["of"] == samples for value in per_channel.values()),
        detail=per_channel,
        reason="" if not offline else "offline mode: no requests were sent",
    )

    # Requirement: the "skill off" condition is proven from the *request payload*,
    # not from the skill list or the system prompt. Every measured sample must
    # have been scanned and none may carry rule text - in the recalled-facts
    # block, in the superseded-values block, or anywhere else in the request.
    payload_evidence = {
        case: {
            "samples": len(checklist[case]["samples"]),
            "scanned": sum(1 for row in checklist[case]["samples"]
                           if (row.get("probe_locations") or {}).get("requests_scanned")),
            "carrying_rule_text": checklist[case].get("samples_carrying_rule_text", 0),
            "locations": [
                {"session_id": row.get("session_id"),
                 "in_recalled_facts_block": (row.get("probe_locations") or {}).get("in_recalled_facts_block"),
                 "in_superseded_block": (row.get("probe_locations") or {}).get("in_superseded_block"),
                 "elsewhere_in_request": (row.get("probe_locations") or {}).get("elsewhere_in_request")}
                for row in checklist[case]["samples"]
            ],
        }
        for case in CASES
    }
    detail["payload_evidence"] = payload_evidence
    total_samples = sum(value["samples"] for value in payload_evidence.values())
    total_scanned = sum(value["scanned"] for value in payload_evidence.values())
    total_carrying = sum(value["carrying_rule_text"] for value in payload_evidence.values())
    if offline:
        report.pending(
            "p5.%s_payload_carries_no_rule_text" % condition,
            "offline mode requested" if args.offline else "no credential available",
            detail=payload_evidence,
        )
    elif condition == "off":
        report.check(
            "p5.off_payload_carries_no_rule_text (sampled %d)" % total_samples,
            total_scanned == total_samples and total_carrying == 0,
            detail={
                "probes": list(RULE_TEXT_PROBES),
                "per_case": payload_evidence,
                "note": (
                    "the off arm has no rule anywhere, so its requests must not contain the "
                    "rule's wording in any block; this is asserted on the recorded payloads"
                ),
            },
            metrics={"samples": total_samples, "scanned": total_scanned,
                     "carrying_rule_text": total_carrying},
            reason="" if total_carrying == 0 else "a request in the off arm carried rule text",
        )
    else:
        report.check(
            "p5.%s_payload_carrying_recorded (sampled %d)" % (condition, total_samples),
            total_scanned == total_samples,
            detail={"probes": list(RULE_TEXT_PROBES), "per_case": payload_evidence,
                    "superseded_rule_facts": superseded_rule_facts},
            metrics={"samples": total_samples, "scanned": total_scanned,
                     "carrying_rule_text": total_carrying},
            reason="" if total_scanned == total_samples else "some samples were not scanned",
        )

    if offline:
        for case in CASES:
            report.pending("p5.%s.%s_measured" % (condition, case),
                           "offline mode requested" if args.offline else "no credential available",
                           detail={"samples_requested": samples})
    else:
        for case in CASES:
            measured = detail["measurements"][case]
            report.check(
                "p5.%s.%s_measured" % (condition, case),
                measured["valid"] == measured["of"] and measured["of"] == samples,
                detail=measured,
                metrics={"hits": measured["hits"], "valid": measured["valid"], "of": measured["of"]},
                reason="" if measured["valid"] == measured["of"] else "some samples produced no answer",
            )

    l3_summary = {
        "status": "not_run" if offline else "run",
        "reason": ("offline mode requested" if args.offline else
                   ("" if not offline else "no credential available")),
        "model": seeded["model"], "api_base": seeded["api_base"],
        "requests": len(recorder.calls),
        "raw_requests": str(raw_path),
    }
    payload = report.write(
        run.artifacts_dir / ("p5-%s-report.json" % condition),
        l3=l3_summary,
        extra={**detail, "requests": recorder.report_view()},
    )
    return {
        "condition": condition,
        "run": run.run_metadata(),
        "fingerprint": run.workspace.get("fingerprint"),
        "model_config": seeded,
        "measurements": detail["measurements"],
        "delivery_channels": detail.get("delivery_channels"),
        "learned_detail": learned_detail,
        "prompt_has_rule": detail["prompt_has_rule"],
        "checks": [{"check": c["check"], "status": c["status"], "reason": c.get("reason", "")}
                   for c in payload["checks"]],
        "summary": payload["summary"],
        "artifacts": {"raw_requests": str(raw_path),
                      "report": str(run.artifacts_dir / ("p5-%s-report.json" % condition))},
    }


def _arm_argv(args: argparse.Namespace, condition: str, samples: int, arm_json: Path,
              log_dir: Path) -> tuple[list[str], Path]:
    """Command line for one isolated arm process."""
    argv = [
        sys.executable, str(Path(__file__).resolve()),
        "--only", condition,
        "--arm-json", str(arm_json),
        "--samples", str(samples),
        "--run-root", str(args.run_root),
    ]
    if args.run_prefix:
        argv += ["--run-prefix", args.run_prefix]
    if args.source_data_dir:
        argv += ["--source-data-dir", args.source_data_dir]
    if args.offline:
        argv.append("--offline")
    if not args.keep:
        argv.append("--no-keep-run-dir")
    log = log_dir / ("p5-arm-%s.log" % condition)
    return argv, log


def run_conditions_isolated(args: argparse.Namespace, samples: int) -> tuple[list[dict], list[dict]]:
    """One OS process per arm.

    The skills package caches its discovery result in a process-global, so two
    arms sharing a process can see each other's skills (T6 found exactly that
    leak). Isolation is therefore a property of the run, not a convention.
    """
    import subprocess

    log_dir = Path(args.arm_log_dir) if args.arm_log_dir else Path(args.run_root) / "p5-arms"
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    processes: list[dict] = []
    for condition in CONDITIONS:
        arm_json = log_dir / ("p5-arm-%s.json" % condition)
        argv, log_path = _arm_argv(args, condition, samples, arm_json, log_dir)
        with log_path.open("a", encoding="utf-8") as log:
            completed = subprocess.run(argv, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
        record = {"condition": condition, "argv": argv, "exit_code": completed.returncode,
                  "log": str(log_path), "arm_json": str(arm_json),
                  "arm_json_written": arm_json.is_file()}
        processes.append(record)
        if arm_json.is_file():
            try:
                results.append(json.loads(arm_json.read_text(encoding="utf-8")))
            except ValueError:
                record["arm_json_written"] = False
    return results, processes


async def main() -> int:
    args = parse_args()
    samples = max(1, int(args.samples))

    # Arm-process mode: measure one condition and hand the result back as JSON.
    if args.arm_json and args.only:
        result = await run_condition(args, args.only, samples)
        Path(args.arm_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.arm_json).write_text(
            gc.redact(json.dumps(result, ensure_ascii=False, default=str)) + "\n", encoding="utf-8")
        failed = any(c["status"] in {"failed", "inconclusive"} for c in result["checks"])
        pending = any(c["status"] == "pending" for c in result["checks"])
        return 1 if failed else (2 if pending else 0)

    arm_processes: list[dict] = []
    if args.only:
        results = [await run_condition(args, args.only, samples)]
    elif args.isolate_arms:
        results, arm_processes = run_conditions_isolated(args, samples)
    else:
        results = [await run_condition(args, condition, samples) for condition in CONDITIONS]

    comparability = arm_comparability(results)
    same_model = comparability["same_model_configuration"]

    aggregate = {
        "gate": GATE,
        "generated_utc": gc.utc_now(),
        "argv": list(sys.argv),
        "samples_per_case": samples,
        "conditions": list(CONDITIONS),
        "cases": list(CASES),
        "note": (
            "minimal comparison: counts with denominators, no improvement ratio is "
            "computed or claimed; the dev case is the request the correction was made "
            "about, the holdout case uses different records seeded after the learning turn"
        ),
        "same_model_configuration": same_model,
        "cross_arm_comparability": comparability,
        "arms_isolated_in_separate_processes": bool(arm_processes),
        "arm_processes": arm_processes,
        "results": results,
        "table": [
            {
                "condition": result["condition"],
                "case": case,
                "hits": result["measurements"][case]["hits"],
                "valid": result["measurements"][case]["valid"],
                "of": result["measurements"][case]["of"],
                "adherence": result["measurements"][case].get("adherence", "n/a"),
                "rule_loaded": result["measurements"][case].get("rule_loaded", 0),
                "via_skill_samples": sum(
                    1 for sample in result["measurements"][case].get("samples") or []
                    if (sample.get("channels") or {}).get("via_skill_or_conversation")
                ),
                "via_facts_samples": sum(
                    1 for sample in result["measurements"][case].get("samples") or []
                    if (sample.get("channels") or {}).get("via_recalled_facts")
                ),
            }
            for result in results for case in CASES
        ],
        "pre_t9_limitations": [
            "The arm names describe the intended rule source, but pre-t9 the learned arm can also "
            "reach the model through the user-fact store (the runtime injects recalled facts into "
            "every session). Its adherence count is still a valid measurement of 'the rule is "
            "active and the reply follows it'; what is provisional is the attribution to the skill "
            "channel alone. The per-sample delivery_channels field records which channel carried "
            "the rule text, so a reader can see this without recomputing it.",
            "The 'fixed' arm is skill-only by construction (a hand-written skill, no fact), and "
            "the 'off' arm never learns the rule at all, so those two arms are unaffected by the "
            "pre-t9 defect.",
            "Anything about disabling a rule is out of scope here (the disabled condition is "
            "blocked in the core demonstration until t9 lands); this comparison only measures "
            "rule-present behaviour.",
        ],
        "failures": [
            {
                "condition": result["condition"],
                "case": case,
                "session_id": sample.get("session_id"),
                "invalid_reason": sample.get("invalid_reason"),
                "failed_assertions": ((sample.get("rule") or {}).get("detail") or {}).get("failed"),
                "reply": gc.clip(sample.get("reply"), 1500),
            }
            for result in results for case in CASES
            for sample in result["measurements"][case].get("samples") or []
            if sample.get("failed_assertions") or not sample.get("valid") or not sample.get("hit")
        ],
    }
    text = gc.redact(json.dumps(aggregate, ensure_ascii=False, indent=2, default=str))
    leaks = gc.scan_for_secrets(text)
    aggregate["credential_scan"] = {"hits": leaks, "clean": not leaks}
    text = gc.redact(json.dumps(aggregate, ensure_ascii=False, indent=2, default=str))
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")

    print("")
    print("condition   case      adherence   loaded   via_skill   via_facts   of")
    for row in aggregate["table"]:
        print("%-11s %-9s %-11s %-8d %-11d %-11d %d" % (
            row["condition"], row["case"], row["adherence"], row["rule_loaded"],
            row["via_skill_samples"], row["via_facts_samples"], row["of"]))
    print("same model configuration across arms: %s" % same_model)
    print("same workspace fingerprint across arms: %s" % comparability["same_workspace_fingerprint"])
    print("credential scan: %s" % ("clean" if not leaks else leaks))
    print("report: " + str(out))
    for result in results:
        print("  %-8s run %s  %s" % (result["condition"], result["run"]["run_id"], result["summary"]))

    pending = any(
        check["status"] == "pending" for result in results for check in result["checks"]
    )
    failed = any(
        check["status"] in {"failed", "inconclusive"} for result in results for check in result["checks"]
    )
    if failed or not comparability["passed"] or leaks:
        return 1
    return 2 if pending else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
