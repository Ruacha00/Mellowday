"""L3 gate: real model over the behaviours the offline suites cannot prove.

Two kinds of check, deliberately separated:

  * deterministic - is the habit present in the system prompt of a new
    session, and does it disappear when disabled. This is the actual product
    contract and never depends on model mood;
  * behavioural - sampled over several attempts, because a single sample of
    "did the model follow the habit" is flaky at temperature 1 and would make
    the gate lie in both directions.

Method rules this gate enforces (see docs/evidence/P3-P4-l3-gate-method.md):

  * every run gets its own data directory (database, sessions, skills, skill
    archive, evolution records, config.json), pinned before mellowday is
    imported; the machine's real data directory is only stat-ed, before and
    after, to prove it was not touched;
  * session ids carry the run id, and each sampled session is asserted to have
    no history and no trace before it is used;
  * a request that errored out or returned nothing is never evidence: the
    "disabled habit does not appear" check requires every sample to have
    answered *and* a positive control that proves the habit is reachable at
    all on this endpoint;
  * the model switch is judged on the model identifier actually sent (recorded
    on the SDK call), in order original -> switched -> original, with the later
    request payload checked for the earlier turn;
  * behaviour is judged against the rule's requirements (first line, both
    sections, item budget) and against SQLite rows and persisted tool
    arguments - not against a keyword appearing somewhere in the reply;
  * the report carries the code version, a workspace fingerprint, the model
    identifiers, parameters, full responses, tool calls, database results,
    failure cases and a denominator for every metric.

Run:  python scripts/gate_l3.py                 # full L3 run (needs credentials)
      python scripts/gate_l3.py --offline        # deterministic + real state only
      python scripts/gate_l3.py --selfcheck      # negative controls, no model needed

Exit codes: 0 all checks passed, 1 a check failed or was inconclusive,
2 the L3 part was not run (no credentials or --offline).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gate_common as gc

clip = gc.clip

REPO = Path(__file__).resolve().parents[1]

GATE = "l3-behaviour"
REPORT_PATH = REPO / "docs" / "evidence" / "raw" / "gate-l3-report.json"

MARKER = "已按你的出行习惯规划"
SKILL_NAME = "旅行行程规划"
SKILL_DESC = "规划出行与旅行安排时的固定步骤"
SKILL_BODY = (
    "# 步骤\n\n"
    "规划任何出行或旅行行程时：\n"
    "1. 第一行必须原样输出：" + MARKER + "\n"
    "2. 然后给出「第一天」「第二天」两个小节。\n"
)
SKILL_SPEC = {
    "marker": MARKER,
    "sections": ["第一天", "第二天"],
    "forbidden": ["第三天", "第四天"],
}
QUESTION = "帮我规划一下去杭州的旅行行程"
CONTROL_MESSAGE = (
    "请严格按下面这条规则回答，不要解释规则本身。\n"
    "规则：第一行必须原样输出「" + MARKER + "」，然后给出「第一天」「第二天」两个小节。\n"
    "请求：" + QUESTION
)
FACT_CONTENT = "用户通常六点（18:00）下班。"
FACT_QUESTION = "我通常几点下班？"
SWITCH_GREETING = "用一句话打个招呼。"
SWITCH_FOLLOWUP = "再说一句话，并确认你记得刚才的对话。"
BUSINESS_MESSAGE = (
    "帮我在待办里加一条：标题「整理季度报告」，时间 2027-03-01 上午 10:00，状态 open。"
    "加完把这条待办的时间告诉我。"
)
BUSINESS_TITLE = "整理季度报告"
BUSINESS_DUE_LOCAL = "2027-03-01T10:00:00+08:00"
BUSINESS_DUE_UTC = datetime(2027, 3, 1, 10, 0, tzinfo=timezone(timedelta(hours=8))).astimezone(
    timezone.utc
)
SUCCESS_WORDS = ("已加", "已创建", "已添加", "加好", "已记录", "已经加", "已为您加", "已帮你加")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attempts", type=int, default=2, help="samples per behavioural check (default 2)")
    parser.add_argument("--run-root", default=str(gc.DEFAULT_RUN_ROOT), help="where run directories are created")
    parser.add_argument("--run-id", default="", help="override the generated run id")
    parser.add_argument("--json-out", default="", help="report path (default: the stable path for an L3 run, the run directory otherwise)")
    parser.add_argument("--source-data-dir", default="", help="the data directory this run must not touch")
    parser.add_argument("--offline", action="store_true", help="no model requests; deterministic checks only")
    parser.add_argument("--selfcheck", action="store_true", help="also run the predicate negative controls")
    parser.add_argument("--no-selfcheck", dest="selfcheck", action="store_false")
    parser.add_argument("--no-keep-run-dir", dest="keep", action="store_false", default=True)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    attempts = max(1, int(args.attempts))

    # The run directory must be pinned before mellowday is imported anywhere.
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

    if not seeded["api_key_present"]:
        offline_reason = "no credential available (MELLOWDAY_API_KEY and the local config are both empty)"
    else:
        offline_reason = ""

    from mellowday import config, paths  # noqa: E402  (after the run directory is pinned)
    from mellowday.storage.store import Store  # noqa: E402
    from mellowday.web_app.service import SessionRegistry  # noqa: E402
    from mellowday.runtime.prompt import build_system_prompt  # noqa: E402
    from mellowday.runtime.skills import (  # noqa: E402
        create_skill_file,
        disable_skill,
        enable_skill,
        format_retrieved_skill_context,
        list_skills,
        reset_skill_cache,
        retrieve_relevant_skills,
    )

    store = Store(data_dir=run.data_dir)
    registry = SessionRegistry(store=store)

    # ------------------------------------------------- deterministic: prompt
    created = create_skill_file(name=SKILL_NAME, description=SKILL_DESC, instructions=SKILL_BODY)
    reset_skill_cache()
    prompt_on = build_system_prompt()
    listed_on = list_skills()
    retrieved_on = [str(hit.get("name")) for hit in retrieve_relevant_skills(QUESTION, limit=3)]
    context_on, _top = format_retrieved_skill_context(QUESTION, limit=3)

    disabled = disable_skill(SKILL_NAME)
    reset_skill_cache()
    prompt_off = build_system_prompt()
    retrieved_off = [str(hit.get("name")) for hit in retrieve_relevant_skills(QUESTION, limit=3)]
    context_off, _top_off = format_retrieved_skill_context(QUESTION, limit=3)

    enabled = enable_skill(SKILL_NAME)
    reset_skill_cache()
    prompt_back = build_system_prompt()
    listed_back = list_skills()

    paths_on = [entry.get("path", "") for entry in listed_on]
    inside_run_dir = all(str(run.data_dir) in str(path) for path in paths_on) if paths_on else False
    advertised_on = SKILL_NAME in prompt_on and SKILL_DESC in prompt_on
    advertised_off = SKILL_NAME not in prompt_off
    advertised_back = SKILL_NAME in prompt_back
    retrieval_on = SKILL_NAME in retrieved_on and SKILL_NAME in context_on
    retrieval_off = SKILL_NAME not in retrieved_off and SKILL_NAME not in context_off
    report.check(
        "deterministic.habit_is_advertised_and_retrievable_only_while_enabled",
        bool(created.get("ok"))
        and advertised_on
        and advertised_off
        and advertised_back
        and retrieval_on
        and retrieval_off
        and bool(disabled.get("ok"))
        and bool(enabled.get("ok"))
        and inside_run_dir,
        detail={
            "created": {key: created.get(key) for key in ("ok", "name", "version", "file")},
            "disabled": {key: disabled.get(key) for key in ("ok", "changed", "archived_to")},
            "enabled": {key: enabled.get(key) for key in ("ok", "changed")},
            "advertised_enabled": advertised_on,
            "advertised_disabled": advertised_off,
            "advertised_reenabled": advertised_back,
            "retrieved_enabled": retrieved_on,
            "retrieved_disabled": retrieved_off,
            "retrieved_context_mentions_skill_enabled": SKILL_NAME in context_on,
            "retrieved_context_mentions_skill_disabled": SKILL_NAME in context_off,
            "retrieved_context_enabled": clip(context_on, 800),
            "rule_body_in_base_prompt": MARKER in prompt_on,
            "delivery_path": (
                "the rule body is not part of the base system prompt; it reaches the "
                "model through the skill tool call, which is why every L3 sample also "
                "records whether the rule text was present in the outbound payload"
            ),
            "skill_files_inside_run_dir": inside_run_dir,
            "skills_inside_run_dir": [str(path) for path in paths_on],
            "skill_names_after_reenable": [entry.get("name") for entry in listed_back],
        },
    )

    # ------------------------------------------ deterministic: tool + database
    offline_evidence = await gc.offline_transaction_checks(store, report)

    # ------------------------------------------------------------- L3 section
    recorder = gc.ModelCallRecorder()
    status = {"status": "not_run", "reason": "", "model": seeded["model"], "api_base": seeded["api_base"]}
    l3_extra: dict[str, object] = {"offline": offline_evidence}

    def l3_pending(reason: str) -> None:
        report.pending("l3.model_control_reproduces_the_habit", reason)
        report.pending("l3.habit_changes_behaviour_when_enabled", reason)
        report.pending("l3.disabled_habit_never_appears", reason)
        report.pending("l3.stored_fact_is_injected_without_a_tool_call", reason)
        report.pending("l3.model_switch_reaches_the_next_request", reason)
        report.pending("l3.business_write_matches_the_database", reason)
        report.pending("l3.deleting_a_session_removes_every_artifact", reason)

    if args.offline or not seeded["api_key_present"]:
        reason = "offline mode requested" if args.offline else offline_reason
        status["reason"] = reason
        l3_pending(reason)
    else:
        recorder.install()
        if not recorder.available:
            status["status"] = "not_run"
            status["reason"] = "the model-call recorder could not be installed: %s" % (
                "; ".join(recorder.install_errors) or "unknown"
            )
            l3_pending(status["reason"])
        else:
            endpoint = gc.probe_endpoint(seeded["api_base"], run.credentials.get("api_key", ""))
            l3_extra["endpoint"] = endpoint
            if not endpoint["ok"]:
                status["status"] = "not_run"
                status["reason"] = "endpoint unreachable: %s" % endpoint.get("error")
                l3_pending(status["reason"])
            else:
                status["status"] = "run"
                try:
                    await run_l3_checks(
                        run, report, registry, store, config, paths, recorder, endpoint,
                        attempts, l3_extra,
                    )
                except Exception as exc:
                    # A crash must still leave evidence: the report is written
                    # below either way, with the exception recorded as a failure.
                    status["runner_exception"] = "%s: %s" % (type(exc).__name__, exc)
                    report.check(
                        "l3.runner_completed_without_an_exception",
                        False,
                        detail={"exception": status["runner_exception"]},
                        reason=status["runner_exception"],
                    )

    # ----------------------------------------------------------- artefacts
    raw_path = run.artifacts_dir / "model-calls.jsonl"
    recorder.dump_raw(raw_path)

    pollution = run.pollution_report()
    report.check(
        "isolation.real_data_directory_untouched",
        pollution["clean"],
        detail=pollution,
        reason="" if pollution["clean"] else "the run changed the machine's real data directory",
    )

    l3_summary = {
        **status,
        "requests": len(recorder.calls),
        "recorder_available": recorder.available,
        "recorder_errors": recorder.install_errors,
        "raw_requests": str(raw_path),
    }
    extra = {
        **l3_extra,
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


async def run_l3_checks(run, report, registry, store, config, paths, recorder, endpoint, attempts, extra) -> None:
    """Every check that needs a real model request."""
    from mellowday.runtime.skills import disable_skill, enable_skill, reset_skill_cache

    # ---------------------------------------------------------- 0. control
    # Disable the habit for the control: the rule may only come from the message.
    disable_skill(SKILL_NAME)
    reset_skill_cache()
    control = await gc.run_turn(registry, run.session_id("control", 0), CONTROL_MESSAGE)
    control_verdict = gc.merge_rule_results(control["reply"], [SKILL_SPEC])
    control_ok = bool(control_verdict["ok"])
    extra["control"] = gc.session_summary(control)
    report.check(
        "l3.model_control_reproduces_the_habit",
        control_ok,
        detail={
            "note": (
                "with the rule inline in the message the model must be able to satisfy it; "
                "without this control, 'the habit did not appear' proves nothing"
            ),
            "sample": gc.session_summary(control),
            "assertions": control_verdict["detail"],
        },
    )

    # ------------------------------------------------- 1. enabled behaviour
    enable_skill(SKILL_NAME)
    reset_skill_cache()
    on_samples = await gc.sample_sessions(
        registry, run, "habit-on", QUESTION, attempts, specs=[SKILL_SPEC],
        recorder=recorder, payload_probes=[MARKER],
    )
    extra["on_samples"] = on_samples
    ok, detail = gc.on_side_verdict(on_samples, min_hits=1)
    report.check(
        "l3.habit_changes_behaviour_when_enabled",
        ok,
        detail={**detail, "samples_ref": "on_samples"},
        metrics={"hits": detail["hits"], "of": detail["of"], "valid": detail["valid"]},
        reason=detail.get("inconclusive_reason", ""),
    )

    # ------------------------------------------------- 2. disabled behaviour
    disable_skill(SKILL_NAME)
    reset_skill_cache()
    off_samples = await gc.sample_sessions(
        registry, run, "habit-off", QUESTION, attempts, specs=[SKILL_SPEC],
        recorder=recorder, payload_probes=[MARKER],
    )
    extra["off_samples"] = off_samples
    ok, detail = gc.off_side_verdict(off_samples, control_ok=control_ok)
    report.check(
        "l3.disabled_habit_never_appears",
        ok,
        detail={**detail, "samples_ref": "off_samples"},
        metrics={"hits": detail["hits"], "of": detail["of"], "valid": detail["valid"]},
        reason=detail.get("inconclusive_reason", "") or detail.get("reason", ""),
    )
    enable_skill(SKILL_NAME)
    reset_skill_cache()

    # ------------------------------------------------------ 3. fact recall
    stored = await gc.call_tool(
        store, "remember_fact", {"content": FACT_CONTENT, "label": "下班时间", "kind": "preference"}
    )
    fact_rows = gc.db_rows(store, "memories", include_done=False)
    seq_before = len(recorder.calls)
    fact_turn = await gc.run_turn(registry, run.session_id("fact", 0), FACT_QUESTION)
    injected = any(
        FACT_CONTENT[:12] in str(call.get("payload_text") or "")
        for call in recorder.calls[seq_before:]
    )
    fact_tokens = ("18:00", "六点")
    extra["fact"] = {**gc.session_summary(fact_turn), "fact_rows": len(fact_rows), "injected": injected}
    report.check(
        "l3.stored_fact_is_injected_without_a_tool_call",
        bool(stored.get("ok"))
        and len(fact_rows) == 1
        and injected
        and any(token in fact_turn["reply"] for token in fact_tokens)
        and not gc.trace_tool_calls(registry, fact_turn["session_id"]),
        detail={
            "stored": {key: stored.get(key) for key in ("ok", "id", "status")},
            "db_rows": len(fact_rows),
            "fact_text_in_outbound_payload": injected,
            "reply_quotes_the_value": [token for token in fact_tokens if token in fact_turn["reply"]],
            "tool_calls_in_trace": gc.trace_tool_calls(registry, fact_turn["session_id"]),
            "sample": gc.session_summary(fact_turn),
        },
    )

    # ------------------------------------------------------ 4. model switch
    original = config.load_model_config().model
    switched = gc.choose_alternate_model(original, endpoint.get("models") or [])
    switch_detail: dict[str, object] = {"original": original, "switched": switched,
                                        "endpoint_models": endpoint.get("models")}
    if not switched:
        report.inconclusive(
            "l3.model_switch_reaches_the_next_request",
            "the endpoint advertises no second model to switch to",
            detail=switch_detail,
        )
    else:
        session = run.session_id("cfg", 0)
        first = await gc.run_turn(registry, session, SWITCH_GREETING)
        after_first = len(recorder.calls)
        config.update_model_config(model=switched)
        switched_config = config.load_model_config()
        second = await gc.run_turn(registry, session, SWITCH_FOLLOWUP)
        after_second = len(recorder.calls)
        config.update_model_config(model=original)
        third = await gc.run_turn(registry, session, SWITCH_FOLLOWUP)
        sequence = recorder.models_sent()
        switch_detail.update(
            {
                "config_model_after_update": switched_config.model,
                "config_file_in_run_dir": str(paths.config_path()),
                "requests_model_sequence": sequence,
                "responses": {
                    "first": gc.session_summary(first),
                    "second": gc.session_summary(second),
                    "third": gc.session_summary(third),
                },
                "history_records": len(registry.history(session)),
                "first_turn_request_seqs": [call["seq"] for call in recorder.calls[:after_first]],
                "second_turn_request_seqs": [call["seq"] for call in recorder.calls[after_first:after_second]],
            }
        )
        ok_switch, switch_verdict = gc.switch_verdict(sequence, original=original, switched=switched)
        prior_user_probe = SWITCH_GREETING[:6]
        prior_reply = str(first["reply"]).strip()
        reply_probe = prior_reply[:10]
        continuity_evidence = {
            "prior_user_message": bool(recorder.payload_contains(prior_user_probe)),
            "prior_assistant_reply": bool(reply_probe) and bool(recorder.payload_contains(reply_probe)),
            "history_has_four_records": len(registry.history(session)) >= 4,
        }
        ok_continuity, continuity_detail = gc.continuity_verdict(continuity_evidence)
        switch_detail["continuity"] = continuity_detail
        switch_detail["switch"] = switch_verdict
        report.check(
            "l3.model_switch_reaches_the_next_request",
            ok_switch and ok_continuity,
            detail=switch_detail,
            reason="" if (ok_switch and ok_continuity) else (switch_verdict.get("reason")
                                                             or continuity_detail.get("reason", "")),
        )

    # ------------------------------------------------- 5. business write path
    samples: list[dict[str, object]] = []
    ok_samples = 0
    hard_failures: list[str] = []
    for index in range(attempts):
        session = run.session_id("business", index)
        # Rows accumulate across samples, so each sample is judged on the rows
        # that appeared *during its own turn* (id delta), never on the total.
        ids_before = {str(row.get("id") or "") for row in gc.db_rows(store, "todos")}
        seq_before = len(recorder.calls)
        turn = await gc.run_turn(registry, session, BUSINESS_MESSAGE)
        request_calls = recorder.calls[seq_before:]
        trace_calls = gc.trace_tool_calls(registry, session)
        creates = [call for call in trace_calls if call.get("name") == "create_todo"]
        new_rows = [
            row
            for row in gc.db_rows(store, "todos")
            if str(row.get("id") or "") not in ids_before
            and str(row.get("title") or "") == BUSINESS_TITLE
        ]
        stored_instants = []
        for candidate in new_rows:
            try:
                stored_instants.append(
                    datetime.fromisoformat(str(candidate.get("due_at"))).astimezone(timezone.utc)
                )
            except ValueError:
                stored_instants.append(None)
        correct_instant = BUSINESS_DUE_UTC in stored_instants
        claims_success = any(word in str(turn["reply"]) for word in SUCCESS_WORDS)
        entry = {
            "session_id": session,
            "valid": gc.sample_is_valid(turn)[0],
            "invalid_reason": gc.sample_is_valid(turn)[1],
            "request_seqs": [int(call["seq"]) for call in request_calls],
            "models_sent": sorted({str(call.get("model") or "") for call in request_calls}),
            "trace_entry_kinds": gc.trace_kinds(registry, session),
            "tool_calls_in_trace": trace_calls,
            "create_tool_calls_in_trace": len(creates),
            "new_rows_during_this_turn": len(new_rows),
            "new_row_due_at": [row.get("due_at") for row in new_rows],
            "stored_instant_matches_2027_03_01T10:00+08:00": correct_instant,
            "reply_claims_success": claims_success,
            "sample": gc.session_summary(turn),
        }
        samples.append(entry)
        if creates and len(new_rows) == 1 and correct_instant:
            ok_samples += 1
        if len(new_rows) > 1:
            hard_failures.append(
                "sample %d wrote %d rows during one request" % (index, len(new_rows))
            )
        if new_rows and not correct_instant:
            hard_failures.append(
                "sample %d stored a different instant: %s" % (index, entry["new_row_due_at"])
            )
        if claims_success and not new_rows:
            hard_failures.append("sample %d claimed success without a new row" % index)
        if new_rows and not creates:
            hard_failures.append(
                "sample %d produced a row without a create_todo entry in the raw record" % index
            )
        if not entry["trace_entry_kinds"]:
            hard_failures.append(
                "sample %d left an empty raw record; the trace reader could not see the turn" % index
            )
        if not entry["valid"]:
            hard_failures.append("sample %d did not answer: %s" % (index, entry["invalid_reason"]))
    extra["business_samples"] = samples
    report.check(
        "l3.business_write_matches_the_database (sampled %d)" % attempts,
        ok_samples >= 1 and not hard_failures,
        detail={"samples": samples, "hard_failures": hard_failures},
        metrics={"samples_with_a_correct_row": ok_samples, "of": attempts,
                 "hard_failures": len(hard_failures)},
        reason=", ".join(hard_failures),
    )

    # ------------------------------------------------------ 6. session delete
    doomed = run.session_id("doomed", 0)
    before = gc.stat_snapshot(paths.sessions_dir())
    await gc.run_turn(registry, doomed, "记住这条会话稍后会被删除。")
    existed = registry.exists(doomed)
    removed = await registry.adrop(doomed)
    leftovers = sorted(path.name for path in paths.sessions_dir().glob(doomed + "*"))
    after = gc.stat_snapshot(paths.sessions_dir())
    diff = gc.snapshot_diff(before, after)
    gone = (
        removed
        and not leftovers
        and not registry.exists(doomed)
        and registry.trace(doomed) == []
        and registry.history(doomed) == []
    )
    report.check(
        "l3.deleting_a_session_removes_every_artifact",
        bool(gone and existed),
        detail={
            "session_existed_before_delete": existed,
            "removed_return_value": removed,
            "leftover_files": leftovers,
            "exists_after": registry.exists(doomed),
            "trace_records_after": len(registry.trace(doomed)),
            "history_records_after": len(registry.history(doomed)),
            "other_session_files_untouched": diff["clean"],
            "sessions_dir_diff": diff,
        },
        reason="" if (gone and existed) else "the deleted session left state behind, or never existed",
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
