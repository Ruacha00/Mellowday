"""Core demonstration of the P3/P4 user flows on a real model.

What this script is for
-----------------------
The gates answer "is this behaviour present, and does it stop when disabled".
The demonstration answers a different question: *can a user actually walk the
flow end to end*, from existing records and current facts, through an explicit
correction and the review of the rule it produces, to a brand new session that
follows it, a repeated correction that must not damage it, an explicit request
that overrides it, an unrelated request that must not load it, disable/enable
and a version rollback, and finally a long conversation that is folded and a
process restart that continues the unfinished task.

Everything runs against a private run directory (see gate_common.RunContext):
database, sessions, skills, skill archive, evolution records and config.json all
live inside it, and the machine's real data directory is only stat-ed.

The rule-review and rule-management steps go through a real web-app process
(python -m mellowday.web_app) over HTTP, because "the user can see and manage
the rule" is a claim about the product surface, not about a function call.

Commands
--------
    python scripts/demo_core.py --offline          # seeds + deterministic steps only
    python scripts/demo_core.py                    # full demonstration (needs credentials)
    python scripts/demo_core.py --phase continue --run-dir <dir> --session <id> --out <file>
                                                   # restart-continuation child process

Exit codes: 0 every check passed, 1 a check failed or was inconclusive,
2 the model-driven part was not run (no credentials or --offline).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Mapping

import demo_support as ds
import gate_common as gc

REPO = Path(__file__).resolve().parents[1]
GATE = "core-demo"
REPORT_PATH = REPO / "docs" / "evidence" / "raw" / "core-demo-report.json"

EVENT_TITLE = "每日站会"
SEED_TODOS = ("写季度报告", "开项目周会", "买生日礼物", "整理收件箱", "续保车险", "预约体检")
FACTS = (
    {"content": "用户通常六点（18:00）下班。", "label": "下班时间", "kind": "preference",
     "reply_probes": ("18:00", "六点")},
    {"content": "用户偏好上午处理需要专注的工作（深度工作），下午安排会议。", "label": "工作节奏",
     "kind": "preference", "reply_probes": ("专注", "深度工作", "上午")},
)
PLAN_ASK = "帮我规划一下明天要做的事。"
CORRECTION = "不对。以后帮我规划的时候，必须先列出当天已有的固定日程，然后只排三个重点任务，不要一次列十几条。"
EDIT_NOTE = "演示：人工审查后补一句执行顺序"
EDIT_SUFFIX = "在给出三个重点任务时，同时用一句话给出建议执行顺序。"
RULE_FACT_TERMS = ("固定日程", "重点任务")
"""The rule's own wording, used only as *fact-channel* probes.

The reply-side assertions are structural (see evaluate_structural_rule) because a
conforming reply may title its sections differently (T6 F2); these two terms stay
because they are what the correction's text contributes to the fact store, and the
disable-side check needs to notice that text arriving through that channel.
"""
def _strip_front_matter(text: str) -> str:
    """Drop the YAML front matter (name/description/version) of a SKILL.md.

    The front matter is metadata, not the rule: the runtime strips it before it
    hands the body to the model, so a probe taken from it can never match the
    activation result (t23: the probe used to be the "description: ..." line and
    the delivery check therefore reported a false "body not delivered").
    """
    lines = str(text or "").splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1:])
    return "\n".join(lines)


_SHORT_PROBE_LENGTH = 6
"""Fallback probe length for a rule whose instructions are all short lines."""

_METADATA_LINE = re.compile(
    r"^(?:---|name|description|version|updated_at|created_at|source|author)\s*:", re.IGNORECASE
)
"""Front-matter style key lines that are metadata rather than rule text."""


def instructions_region(body: str) -> str:
    """The rule instructions of a SKILL.md, without metadata or evolution notes.

    The body carries a stripped front matter plus "## Creation Evidence" /
    "## Evolution Notes" sections with timestamps and audit lines; a probe taken
    from either would be body text but not rule text.
    """
    lines: list[str] = []
    for line in _strip_front_matter(body).splitlines():
        if line.strip().startswith("## "):
            break
        lines.append(line)
    return "\n".join(lines)


def _as_sample_list(record) -> list[dict]:
    """Accept both shapes a step may record: one summary dict or a list of them."""
    if isinstance(record, dict):
        samples = record.get("samples")
        if isinstance(samples, list):
            return [sample for sample in samples if isinstance(sample, dict)]
        return [record] if record else []
    if isinstance(record, list):
        return [sample for sample in record if isinstance(sample, dict)]
    return []


def run_selfcheck(report: gc.Report) -> None:
    """Negative controls for the judgement this demonstration measures with.

    evaluate_structural_rule() decides whether a reply satisfies the planning
    rule, and the same function produces the denominators in the P5 comparison.
    A measurement tool without a negative control makes "is the judgement right"
    an unverifiable assumption (T14 review, N2), so each control below feeds it a
    reply whose verdict is known in advance - including the two cases that broke
    earlier versions: a conforming reply with different section titles, and a
    reply that lists three priorities *plus* the remaining to-dos.
    """
    event = EVENT_TITLE
    todos = SEED_TODOS

    controls = [
        (
            "selfcheck.structural_judgement_accepts_a_conforming_reply",
            "**固定日程**\n- 09:30 " + event + "\n\n**重点任务**\n1. 写季度报告\n2. 开项目周会\n3. 买生日礼物",
            True,
        ),
        (
            "selfcheck.structural_judgement_ignores_section_titles",
            "**已排日程**\n- 09:30 " + event + "（已排日历）\n\n**今天先做这三件**\n1. 写季度报告\n2. 开项目周会\n3. 买生日礼物",
            True,
        ),
        (
            "selfcheck.structural_judgement_accepts_three_priorities_plus_the_rest",
            "**固定日程**\n- 09:30 " + event + "\n\n**重点任务**\n1. 写季度报告\n2. 开项目周会\n3. 买生日礼物\n\n**其余待办**\n1. 整理收件箱\n2. 续保车险\n3. 预约体检",
            True,
        ),
        (
            "selfcheck.structural_judgement_rejects_a_long_list",
            "**固定日程**\n- 09:30 " + event + "\n\n**全部待办**\n1. 写季度报告\n2. 开项目周会\n3. 买生日礼物\n"
            "4. 整理收件箱\n5. 续保车险\n6. 预约体检\n7. 取快递\n8. 交房租",
            False,
        ),
        (
            "selfcheck.structural_judgement_rejects_four_priorities",
            "**固定日程**\n- 09:30 " + event + "\n\n**重点任务**\n1. 写季度报告\n2. 开项目周会\n3. 买生日礼物\n4. 整理收件箱",
            False,
        ),
        (
            "selfcheck.structural_judgement_rejects_a_reply_without_real_records",
            "明天可以这样安排：上午专注工作，下午开会，傍晚买东西。",
            False,
        ),
    ]
    for name, reply, expected in controls:
        verdict = evaluate_structural_rule(reply, event_title=event, todos=todos)
        report.check(
            name,
            bool(verdict["ok"]) is expected,
            detail={
                "expected_satisfied": expected,
                "actual_satisfied": bool(verdict["ok"]),
                "failed_assertions": verdict["detail"]["failed"],
                "evidence": verdict["detail"]["evidence"],
            },
            reason="" if bool(verdict["ok"]) is expected else "the structural judgement disagreed with the known verdict",
        )

    # N5's exact defect shape: the rule text arriving *only* through the injected
    # recalled-facts block. The old demo probe reported payload_leaks=0 for this
    # payload; the shared three-segment classifier must report a leak.
    rule_sentence = "先列出当天已有的固定日程，然后只排三个重点任务"
    facts_only = [
        {"seq": 1, "payload_text": (
            "system prompt without the rule\n\n<system-reminder>\n"
            "Recalled facts about the user (current values from the memory store):\n"
            "- 规划习惯 [preference]: " + rule_sentence + "\n"
            "</system-reminder>\n用户：帮我规划一下明天。\n"
        )},
    ]
    clean = [
        {"seq": 1, "payload_text": (
            "system prompt without the rule\n\n<system-reminder>\n"
            "Recalled facts about the user (current values from the memory store):\n"
            "- 下班时间 [preference]: 用户通常六点下班。\n"
            "</system-reminder>\n用户：帮我规划一下明天。\n"
        )},
    ]
    located = gc.payload_probe_locations(facts_only, [rule_sentence, "固定日程", "重点任务"])
    located_clean = gc.payload_probe_locations(clean, [rule_sentence, "固定日程", "重点任务"])
    report.check(
        "selfcheck.leak_judgement_reports_a_rule_only_in_the_facts_segment",
        bool(located["present_anywhere"])
        and "固定日程" in located["in_recalled_facts_block"]
        and not located["in_superseded_block"]
        and not located["elsewhere_in_request"]
        and not located_clean["present_anywhere"],
        detail={
            "facts_only_sample": located,
            "clean_sample": located_clean,
            "note": (
                "the pre-t23 demo probe looked for the skill name and a body snippet only, so "
                "this payload scored 'no leak'; the shared classifier must report it"
            ),
        },
    )

    # t23's first defect shape: the probe used to be taken from the *front
    # matter* of SKILL.md, which the runtime strips before it hands the rule to
    # the model, so "the rule was delivered" degraded to a false negative.  The
    # synthetic body below has a description line longer than every instruction
    # line, which is exactly what made the old selector pick it.
    front_matter_line = "description: " + "很长的描述行" * 6
    synthetic_body = "\n".join([
        "---",
        "name: demo_policy",
        front_matter_line,
        "version: 0.1.0",
        "---",
        "",
        "# Skill Instructions",
        "",
        "1. 先列出当天已有的固定日程。",
        "2. 随后只挑选三个重点任务。",
        "3. 不要一次列出十几条。",
        "",
        "## Creation Evidence",
        "用户反馈：随便写的一句话，不应被选为探针。",
    ])
    probe = pick_body_probe(synthetic_body, "很长的描述行" * 6)
    instruction_lines = ("1. 先列出当天已有的固定日程。", "2. 随后只挑选三个重点任务。", "3. 不要一次列出十几条。")
    # A body whose instruction lines are all shorter than the default probe
    # length: the selector must still return an instruction probe instead of
    # silently degrading to "" (which is what a hard-coded length would do).
    short_body = "\n".join([
        "---", "name: demo_policy", "description: 短规则", "---", "",
        "# Skill Instructions", "", "1. 先列日程。", "2. 排三个重点。", "3. 不要列十几条。",
    ])
    short_probe = pick_body_probe(short_body, "短规则")
    report.check(
        "selfcheck.body_probe_comes_from_the_instructions_not_the_front_matter",
        bool(probe) and probe not in front_matter_line
        and any(probe in line for line in instruction_lines)
        and bool(short_probe) and short_probe not in "短规则",
        detail={"chosen_probe": probe, "front_matter_line": front_matter_line,
                "short_body_probe": short_probe,
                "note": "the runtime strips the front matter, so a probe taken from it can never match"},
    )

    # t23's second shape: the runtime delivers the rule body through the *tool
    # result* of the skill tool, not through the request payloads.  A delivery
    # judgement that only reads the request payloads reports "not delivered" for
    # a rule the model did receive.
    tool_calls = [{"name": "skill", "arguments": '{"name": "demo_policy"}'}]
    tool_results = [{"name": "skill", "result": "# Skill Instructions\n\n3. 不要一次列出十几条。"}]
    delivery = rule_delivery(
        [{"seq": 1, "payload_text": "system prompt advertising demo_policy without its body"}],
        rule_name="demo_policy", body_probe="3. 不要一次列出十几条。",
        sample={"tool_calls": tool_calls, "tool_results": tool_results},
    )
    report.check(
        "selfcheck.delivery_is_seen_even_when_only_the_tool_result_carries_the_rule",
        not delivery["body_probe_in_payload"]
        and delivery["body_probe_in_tool_results"]
        and delivery["skill_tool_call_present"],
        detail={"delivery": delivery,
                "note": "same channel shape that made the t23 follow sample look undelivered"},
    )

    # The predicates the gates share are checked the same way: each one is fed an
    # input on which the first-generation gate logic returned a pass.
    gc.run_predicate_selfcheck(report)


def pick_body_probe(body: str, description: str = "", *, length: int = 16) -> str:
    """The longest rule line of the current body the description does not carry.

    Derived at runtime on purpose (T6 F3): a hard-coded phrase silently stops
    matching as soon as the online maintainer rewrites the rule - in another
    language, for instance - and every "the rule was delivered" assertion then
    quietly degrades to the skill name.

    t23: the probe must come from the *instructions*, so front matter (name /
    description / version) and headings are skipped.  A front-matter line is
    stripped by the runtime before the skill is handed to the model, so a probe
    taken from it reports "the rule was never delivered" even when it was.
    """
    description = str(description or "")
    region = instructions_region(body) or str(body or "")
    lines = [
        line.strip() for line in region.splitlines()
        if line.strip() and not line.strip().startswith("#")
        and not _METADATA_LINE.match(line.strip())
    ]
    for minimum in (length, _SHORT_PROBE_LENGTH):
        candidates = [line for line in lines if len(line) >= minimum]
        for line in sorted(candidates, key=len, reverse=True):
            if line[:minimum] not in description:
                return line[:minimum]
    # No instruction line long enough to be a distinctive probe: report an empty
    # probe rather than a substring that matches everywhere.
    return ""


_TOP_ITEM = re.compile(
    # same shape as gate_common's item parser: a bullet needs whitespace and must
    # not open a bold run, and only the shallowest indentation counts
    r"^\s*(?:[-*\u2022\u00b7](?!\*)\s+|\d{1,2}\s*[.\u3001)\uff08\uff09]\s*|[\u2460-\u2469]\s*)\S"
)


def reply_blocks(reply: str) -> list[str]:
    """Split a reply into blocks separated by blank lines (headings included)."""
    blocks: list[str] = []
    current: list[str] = []
    for line in str(reply or "").splitlines():
        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def evaluate_structural_rule(
    reply: str,
    *,
    event_title: str,
    todos: Sequence[str],
    priority_items: int = 3,
    max_items_per_block: int = 10,
) -> dict:
    """Judge a reply against what the rule *requires*, not how it words it.

    The rule (from the user's correction) is: first the day's already fixed
    schedule, then only three priority tasks, and never a long list. Section
    titles are deliberately not asserted (T6 F2); what is asserted is that a
    block presents exactly three priority tasks drawn from the real to-dos,
    that the real schedule entry is listed, and that no block dumps a long list
    ("十几条" - a six-item "everything else" block is not a long list).
    """
    text = str(reply or "")
    blocks = reply_blocks(text)
    event_in_reply = bool(event_title) and event_title in text
    todos_found = [title for title in todos if title in text]
    schedule_blocks = [block for block in blocks if event_title and event_title in block]

    def block_lines(block: str) -> list[str]:
        """Top-level item lines of a block, minus the schedule entry itself."""
        lines = [line for line in str(block).splitlines() if _TOP_ITEM.match(line)]
        if event_title:
            lines = [line for line in lines if event_title not in line]
        return lines

    item_counts = []
    for block in blocks:
        lines = block_lines(block)
        item_counts.append({
            "items": len(lines),
            "block": gc.clip(block, 200),
            "excerpt": [gc.clip(line, 80) for line in lines][:12],
        })
    max_items = max((entry["items"] for entry in item_counts), default=0)

    # A block "presents three priority tasks" when it holds exactly three
    # top-level items and at least two of them are real to-do titles. This is
    # deliberately not "the block with the most to-do hits": a reply that ends
    # with "everything else: 1..6" has more hits there than in its priority list.
    def presents_three_priorities(block: str) -> bool:
        lines = block_lines(block)
        if len(lines) != priority_items:
            return False
        real = sum(1 for line in lines if any(title in line for title in todos))
        return real >= 2

    priority_candidates = [
        block for block in blocks
        if presents_three_priorities(block) and not (event_title and event_title in block)
    ]
    priority_block = priority_candidates[0] if priority_candidates else ""
    priority_lines = block_lines(priority_block) if priority_block else []

    assertions = {
        "real_calendar_entry_present": event_in_reply,
        "calendar_entry_listed": bool(schedule_blocks),
        "at_least_3_real_todos_adopted": len(todos_found) >= 3,
        "a_block_presents_exactly_%d_priority_tasks" % priority_items: bool(priority_candidates),
        "no_block_lists_more_than_%d_items" % max_items_per_block: max_items <= max_items_per_block,
    }
    detail = {
        "assertions": assertions,
        "failed": sorted(name for name, ok in assertions.items() if not ok),
        "evidence": {
            "blocks": item_counts,
            "event_title": event_title,
            "event_in_reply": event_in_reply,
            "todos_adopted": todos_found,
            "todos_defined": len(todos),
            "priority_block": gc.clip(priority_block, 300),
            "priority_block_items": len(priority_lines),
            "priority_block_items_excerpt": [gc.clip(line, 90) for line in priority_lines],
            "priority_blocks_found": len(priority_candidates),
            "max_items_in_any_block": max_items,
            "thresholds": {
                "priority_items": priority_items,
                "priority_items_min_real_todos": 2,
                "min_real_todos": 3,
                "max_items_per_block": max_items_per_block,
            },
            "note": (
                "structural: no section title is asserted. A block qualifies as the "
                "priority list when it holds exactly %d top-level items and at least two "
                "of them are real to-do titles; 'no long list' is %d items in one block, "
                "not five, because a six-item 'everything else' list is not 十几条"
                % (priority_items, max_items_per_block)
            ),
        },
    }
    return {"ok": all(assertions.values()), "detail": detail}


UNRELATED_ASK = "帮我记一条待办：明天上午十点去取快递。"
UNRELATED_ASKS = (UNRELATED_ASK, "今天天气怎么样？")
"""Two unrelated shapes: a record-keeping request and a plain question.

t14 found the planning rule reaching an unrelated request's payload
(<retrieved_skills> with score 0.085); t19 raised the retrieval gate
(min_score 0.15 + at least two multi-character terms), so this row is
re-measured from the payload rather than from the skill list.
"""
OVERRIDE_ASK = "这次请把明天所有待办都列出来，不要只排三个。"
TEMP_ASK = "这次先只要一句话概括明天的重点，也不用记住这条要求。"
TASK_TITLE = "写季度报告大纲"
FOLD_TURN_1 = "帮我推进季度报告：先在待办里建一条「" + TASK_TITLE + "」，然后在回复里写出大纲的三条要点。"
FOLD_TURN_2 = "第二条再展开一点，加上要对比的两个数据口径。"
FOLD_TURN_3 = "继续，把第三条也写出来，并确认那条待办还在。"
RESTART_ASK = "请用一句话说明我们正在推进的任务标题，以及下一步要做什么。"
SUCCESS_WORDS = ("已加", "已创建", "已添加", "加好", "已记录", "已经加")

PRIOR_FACT_CHANNEL_OBSERVATIONS = (
    "l3-learning run 20260918T115840Z-f535: the correction wrote fact label 规划偏好 and the "
    "disable side carried the rule through the fact channel in 2/2 requests",
    "l3-learning run 20260918T120611Z-7a79: fact label 规划方式, disable side 2/2 through facts",
    "l3-learning run 20260918T121315Z-f8f1 (after t1-t3): duplicate fact written, disable side 2/2 "
    "through facts",
    "core-demo run 20260918T121554Z-31d1: one rule fact written and injected into every session",
)
"""Observed in earlier runs of this flow; each is reproducible from its run directory."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attempts", type=int, default=2, help="samples for the disable/enable behaviour checks")
    parser.add_argument("--run-root", default=str(gc.DEFAULT_RUN_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--json-out", default="", help="report path (default: the stable path for a model run, the run directory otherwise)")
    parser.add_argument("--source-data-dir", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--selfcheck", action="store_true",
        help="run the executable negative controls (structural judgement + shared predicates) and exit",
    )
    parser.add_argument("--no-keep-run-dir", dest="keep", action="store_false", default=True)
    # restart-continuation child mode
    parser.add_argument("--phase", default="all", choices=("all", "continue"))
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--session", default="")
    parser.add_argument("--out", default="")
    return parser.parse_args()


def tomorrow_local_iso(hour: int, minute: int) -> str:
    now = datetime.now().astimezone()
    target = datetime.combine((now + timedelta(days=1)).date(), clock_time(hour, minute))
    return target.replace(tzinfo=now.tzinfo).isoformat()


# --------------------------------------------------------------- child phase


def continue_phase(args: argparse.Namespace) -> int:
    """Load the session in a brand new process and continue the unfinished task."""
    if not args.run_dir or not args.session:
        print("--phase continue needs --run-dir and --session")
        return 2
    run_root = Path(args.run_dir)
    data_dir = run_root / "data"
    import os

    os.environ["MELLOWDAY_DATA_DIR"] = str(data_dir)
    os.environ["MELLOWDAY_ENV_FILE"] = ""
    gc.ensure_src_on_path()

    from mellowday import paths
    from mellowday.runtime import sessions as session_store
    from mellowday.storage.store import Store
    from mellowday.web_app.service import SessionRegistry

    store = Store(data_dir=data_dir)
    registry = SessionRegistry(store=store)
    saved = session_store.load_session(args.session) or {}
    messages = saved.get("openaiMessages") if isinstance(saved.get("openaiMessages"), list) else []
    rolled = json.dumps(messages, ensure_ascii=False)

    result = asyncio.run(gc.run_turn(registry, args.session, RESTART_ASK))
    payload = {
        "session_id": args.session,
        "data_dir": str(data_dir),
        "restored_message_count": len(messages),
        "task_title_in_restored_state": TASK_TITLE in rolled,
        "restored_has_user_turns": sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user"),
        "reply": result.get("reply", ""),
        "tools": [tool.get("name") for tool in result.get("tools") or []],
        "errors": result.get("errors") or [],
        "sessions_dir": str(paths.sessions_dir()),
        "history_records": len(registry.history(args.session)),
    }
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("restart phase: restored %d messages, reply %d chars" % (payload["restored_message_count"], len(payload["reply"])))
    return 0 if not payload["errors"] else 1


# ------------------------------------------------------------------- helpers


def retrieval_block(payload: str) -> str:
    """The retrieved-skills block of one outbound payload, when it has one."""
    text = str(payload or "")
    start = text.find("<retrieved_skills>")
    if start < 0:
        return ""
    end = text.find("</retrieved_skills>", start)
    return text[start: end if end > 0 else start + 2000]


def rule_delivery(calls, *, rule_name: str, body_probe: str, sample: Mapping[str, Any] | None = None) -> dict:
    """Was the rule actually *loaded* for these requests (not just advertised)?

    The system prompt always advertises an enabled skill (name + description), so
    the mere presence of the name in a payload proves nothing about whether the
    rule was retrieved and handed to the model. What counts here is the
    retrieved-skills block, a skill tool call, or a phrase that only exists in
    the rule body.

    t23: the runtime hands the body over through the *tool result* of the skill
    tool, so the channels are recorded separately (request payloads vs tool
    results); reporting only the request payloads made a delivered rule look
    undelivered.  Pass the sample to fill the tool-result fields in.
    """
    payloads = [str(call.get("payload_text") or "") for call in calls]
    blocks = [retrieval_block(payload) for payload in payloads]
    joined = " ".join(payloads)
    tool_results = " ".join(
        str((tool or {}).get("result") or "") for tool in (sample or {}).get("tool_results") or []
    )
    skill_calls = [
        tool for tool in (sample or {}).get("tool_calls") or []
        if str((tool or {}).get("name") or "") == "skill"
    ]
    # An empty probe would match every string ("'x' in y" is not a probe), so the
    # arms without a rule must report "not delivered" explicitly.
    return {
        "retrieved_block_mentions_rule": bool(rule_name) and any(rule_name in block for block in blocks),
        "body_probe_in_payload": bool(body_probe) and body_probe in joined,
        "body_probe_in_tool_results": bool(body_probe) and body_probe in tool_results,
        "skill_tool_call_present": bool(skill_calls),
        "system_prompt_advertises_rule": bool(rule_name) and any(rule_name in payload for payload in payloads),
        "probes": {"rule_name": rule_name, "body_probe": body_probe},
        "retrieved_blocks": [gc.clip(block, 600) for block in blocks if block],
    }


class Demo:
    """One isolated demonstration run."""

    def __init__(self, run: gc.RunContext, report: gc.Report, *, attempts: int = 2) -> None:
        self.run = run
        self.report = report
        self.attempts = max(1, int(attempts))
        self.recorder = gc.ModelCallRecorder()
        self.extra: dict[str, object] = {}
        self.store = None
        self.registry = None
        self.server: ds.RealServer | None = None
        self.learned_names: list[str] = []
        self.baseline_names: list[str] = []

    # ------------------------------------------------------------- utilities

    def all_calls(self) -> list[dict]:
        return list(self.recorder.calls)

    def calls_for(self, seqs) -> list[dict]:
        wanted = set(int(value) for value in seqs or [])
        return [call for call in self.recorder.calls if int(call["seq"]) in wanted]

    async def turn(self, prefix: str, message: str, *, index: int = 0, approve: bool = True,
                   probes: tuple[str, ...] = ()) -> dict:
        """One turn in a fresh session, with delivery evidence attached."""
        session_id = self.run.session_id(prefix, index)
        freshness = gc.session_freshness(self.registry, session_id)
        seq_before = len(self.recorder.calls)
        result = await gc.run_turn(self.registry, session_id, message, approve=approve)
        calls = self.recorder.calls[seq_before:]
        summary = gc.session_summary(result)
        summary["freshness"] = freshness
        summary["request_seqs"] = [int(call["seq"]) for call in calls]
        summary["channels"] = gc.payload_channel_evidence(
            calls, probes, fact_probes=(EVENT_TITLE,)
        )
        summary["models_sent"] = sorted({str(call.get("model") or "") for call in calls})
        return summary

    async def turn_in_session(self, session_id: str, message: str, *, approve: bool = True,
                              probes: tuple[str, ...] = ()) -> dict:
        seq_before = len(self.recorder.calls)
        result = await gc.run_turn(self.registry, session_id, message, approve=approve)
        calls = self.recorder.calls[seq_before:]
        summary = gc.session_summary(result)
        summary["request_seqs"] = [int(call["seq"]) for call in calls]
        summary["channels"] = gc.payload_channel_evidence(calls, probes, fact_probes=(EVENT_TITLE,))
        return summary

    def rule_texts(self) -> dict[str, str]:
        from mellowday.runtime.skills import list_skills

        bodies: dict[str, str] = {}
        for entry in list_skills():
            path = Path(str(entry.get("path") or ""))
            try:
                bodies[str(entry.get("name"))] = path.read_text(encoding="utf-8")
            except OSError:
                bodies[str(entry.get("name"))] = ""
        return bodies

    def skill_entries(self) -> list[dict]:
        from mellowday.runtime.skills import list_skills

        return list_skills()

    def fact_rows(self) -> list[dict]:
        return gc.db_rows(self.store, "memories", include_done=False)


# ------------------------------------------------------------------- steps


async def run_offline_steps(demo: Demo) -> None:
    """Seeding and the deterministic half of the flows (no model involved)."""
    report, run = demo.report, demo.run
    from mellowday.runtime.skills import create_skill_file, disable_skill, enable_skill, reset_skill_cache

    # ---------------------------------------------------- 1. business seed
    event = await gc.call_tool(
        demo.store, "create_calendar_event",
        {"title": EVENT_TITLE, "due_at": tomorrow_local_iso(9, 30), "status": "scheduled",
         "detail": "每天早上的固定站会"},
    )
    todo_ids = {}
    for title in SEED_TODOS:
        created = await gc.call_tool(
            demo.store, "create_todo",
            {"title": title, "due_at": tomorrow_local_iso(0, 0), "status": "open"},
        )
        todo_ids[title] = str(created.get("id") or "")
    facts = []
    for fact in FACTS:
        stored = await gc.call_tool(
            demo.store, "remember_fact",
            {"content": fact["content"], "label": fact["label"], "kind": fact["kind"]},
        )
        facts.append({"label": fact["label"], "ok": stored.get("ok"), "id": stored.get("id")})
    rows = gc.db_rows(demo.store, "todos")
    event_rows = gc.db_rows(demo.store, "calendar")
    demo.extra["seed"] = {
        "event": {"ok": event.get("ok"), "id": event.get("id"), "due_at_local": event.get("due_at_local")},
        "todos": [row.get("title") for row in rows],
        "facts": facts,
        "todo_ids": todo_ids,
    }
    report.check(
        "demo.business_seed_is_real",
        bool(event.get("ok")) and len(event_rows) == 1 and len(rows) == len(SEED_TODOS)
        and all(row.get("ok") for row in facts),
        detail=demo.extra["seed"],
        metrics={"todos": len(rows), "of": len(SEED_TODOS), "calendar": len(event_rows), "facts": len(facts)},
    )

    # ------------------------------------- 4. rule review/edit (HTTP) is later
    # --------------------------------------------- 9a. disable side, part 1
    # (the deterministic halves of disable/enable/rollback are done in the L3
    #  section, because they need the learned rule to exist)


async def run_l3_steps(demo: Demo) -> None:
    """Everything that needs a real model."""
    report, run = demo.report, demo.run
    from mellowday.runtime.prompt import build_system_prompt
    from mellowday.runtime.skills import (
        disable_skill, enable_skill, reset_skill_cache, restore_skill_version,
    )

    probes = (EVENT_TITLE,)

    # ------------------------------------------------- 2. plan from real data
    plan = await demo.turn("plan", PLAN_ASK, probes=probes)
    demo.extra["plan_turn"] = plan
    todo_hits = [title for title in SEED_TODOS if title in str(plan.get("reply") or "")]
    reply_text = str(plan.get("reply") or "")
    fact_hits = [
        fact["label"] for fact in FACTS
        if any(probe in reply_text for probe in fact["reply_probes"])
    ]
    payload_facts: list[str] = []
    calls = demo.calls_for(plan.get("request_seqs"))
    if calls:
        joined = " ".join(str(call.get("payload_text") or "") for call in calls)
        payload_facts = [fact["label"] for fact in FACTS if fact["content"][:12] in joined]
    payload_fact = len(payload_facts) == len(FACTS)
    tools_used = [tool.get("name") for tool in plan.get("tool_calls") or []]
    report.check(
        "demo.planner_reads_real_records_and_current_facts",
        gc.sample_is_valid(plan)[0]
        and EVENT_TITLE in str(plan.get("reply") or "")
        and len(todo_hits) >= 3
        and bool(fact_hits)
        and payload_fact,
        detail={
            "sample": plan,
            "calendar_event_in_reply": EVENT_TITLE in reply_text,
            "todos_in_reply": todo_hits,
            "facts_reflected_in_reply": fact_hits,
            "facts_in_outbound_payload": payload_facts,
            "fact_probes_used": [fact["reply_probes"] for fact in FACTS],
            "tool_calls": tools_used,
        },
        # Two different denominators used to share the key "of" in this one dict
        # (the later key won), so the report printed "todos 6/2".  Name them.
        metrics={"todos_in_reply": len(todo_hits), "todos_of": len(SEED_TODOS),
                 "facts_reflected": len(fact_hits), "facts_of": len(FACTS)},
        reason="" if gc.sample_is_valid(plan)[0] else gc.sample_is_valid(plan)[1],
    )

    # ------------------------- 3. the correction, and the rule it produces
    session = plan["session_id"]
    facts_before_correction = gc.db_rows(demo.store, "memories")
    correction = await demo.turn_in_session(session, CORRECTION, approve=True, probes=probes)
    reset_skill_cache()
    after = demo.skill_entries()
    learned = [entry for entry in after if str(entry.get("name")) not in demo.baseline_names]
    demo.learned_names = [str(entry.get("name")) for entry in learned]
    bodies = demo.rule_texts()
    applied = [event for event in (correction.get("learning_events") or [])
               if str(event.get("type")) == "skill_candidate_applied"]
    proposed = [event for event in (correction.get("learning_events") or [])
                if str(event.get("type")) == "skill_candidate_proposed"]
    inside_run_dir = all(str(run.data_dir) in str(entry.get("path") or "") for entry in learned) and bool(learned)
    demo.extra["correction"] = {
        "session_id": session, "sample": correction,
        "learned": [{key: entry.get(key) for key in ("name", "version", "enabled", "path")} for entry in learned],
        "bodies": {name: gc.clip(body, 1500) for name, body in bodies.items()},
    }
    report.check(
        "demo.correction_is_confirmed_and_learned",
        bool(learned) and bool(applied) and bool(proposed) and bool(correction.get("confirmations"))
        and inside_run_dir,
        detail=demo.extra["correction"],
        metrics={"skills_after": len(after), "learned": len(learned),
                 "confirmations": len(correction.get("confirmations") or [])},
        reason="" if learned else "the correction produced no skill artifact",
    )

    from gate_l3_learning import assess_confirmed_migration
    migration = assess_confirmed_migration(
        facts_before_correction, gc.db_rows(demo.store, "memories"),
        correction.get("learning_events") or [], correction.get("confirmations") or [],
    )
    demo.extra["confirmed_fact_migration"] = migration
    if migration["status"] == "inconclusive":
        demo.extra["confirmed_fact_migration"] = {
            **migration, "status": "pending", "required_for_this_demo": False,
            "reason": "This demo does not request source-memory migration; the dedicated learning gate covers it.",
        }
    else:
        report.check("demo.confirmed_source_memories_migrate", migration["status"] == "passed",
                     detail=migration, reason=migration["reason"])

    duplicated_facts = [
        {"label": row.get("title"), "content": gc.clip(row.get("detail"), 240)}
        for row in demo.fact_rows()
        if any(term in str(row.get("detail") or "") for term in RULE_FACT_TERMS)
    ]
    demo.extra["fact_channel_after_correction"] = {
        "active_facts": len(demo.fact_rows()),
        "facts_carrying_the_rule": duplicated_facts,
        "note": (
            "the user-fact store is injected into every session regardless of any "
            "skill's enabled state; a duplicate write here makes 'disable the habit' "
            "untrue even when the skill side is off"
        ),
    }
    demo.extra["fact_channel_after_correction"]["ruling"] = (
        "Only explicitly proposed source_memory_ids shown with original text in the accepted "
        "confirmation may migrate after a successful skill write. Related facts stay intact; "
        "payload leakage is still independently judged below."
    )
    report.check(
        "demo.correction_does_not_duplicate_the_rule_into_the_fact_store",
        not migration["errors"],
        detail={"migration": migration, "text_matches_for_payload_followup": duplicated_facts,
                "note": "Text overlap alone does not establish a duplicate instruction; "
                        "unselected objective facts must survive. Disable-side payload checks "
                        "below independently fail on actual rule leakage."},
        reason=migration["reason"] if migration["errors"] else "",
    )

    if not learned:
        for name in (
            "demo.rule_is_reviewable_and_editable_over_http",
            "demo.new_session_follows_the_rule",
            "demo.repeated_feedback_keeps_the_edited_rule",
            "demo.temporary_request_is_not_learned",
            "demo.explicit_request_overrides_the_habit",
            "demo.unrelated_request_does_not_load_the_rule (sampled %d)"
            % len(UNRELATED_ASKS),
            "demo.disabled_rule_leaves_prompt_and_skill_channel",
            "demo.disabled_rule_leaves_no_rule_text_in_the_payload (sampled %d)" % demo.attempts,
            "demo.disabled_rule_stops_changing_behaviour (sampled %d)" % demo.attempts,
            "demo.enabled_rule_changes_behaviour_again",
            "demo.version_rollback_restores_the_earlier_body",
            "demo.folding_replaces_history_with_folded_memory",
            "demo.session_continues_after_folding",
            "demo.session_continues_after_restart",
        ):
            report.inconclusive(name, "no rule was learned, so this step could not run")
        return

    primary = demo.learned_names[0]
    quoted = urllib.parse.quote(primary, safe="")

    # Each step group is guarded on its own: one broken step must not hide the
    # evidence of the others, and the report has to say which group failed.
    await guarded(report, "demo.review_step_completed",
                  demo_review_rule_over_http(demo, primary, quoted))
    await guarded(report, "demo.behaviour_steps_completed",
                  demo_behaviour_steps(demo, primary, quoted, probes))

    # ---------------------------------------------- 10. folding and restart
    await guarded(report, "demo.folding_steps_completed",
                  demo_folding_and_restart(demo, probes))


async def guarded(report: gc.Report, name: str, coroutine) -> None:
    """Run one step group; a crash becomes a recorded failure, not a silent stop."""
    import traceback

    try:
        await coroutine
    except Exception as exc:
        detail = {"exception": "%s: %s" % (type(exc).__name__, exc),
                  "traceback": gc.clip(traceback.format_exc(), 2500)}
        report.check(name, False, detail=detail, reason=detail["exception"])


async def demo_review_rule_over_http(demo: Demo, primary: str, quoted: str) -> None:
    """4. the user reviews the learned rule and edits it through the product API."""
    report, run = demo.report, demo.run
    from mellowday.runtime.skills import reset_skill_cache

    # The detail endpoints answer with the rule body under "body"; the write
    # endpoint takes "instructions". Both are read here exactly as the page does.
    listing = demo.server.get("/api/skills")
    detail = demo.server.get("/api/skills/" + quoted)
    body_before = str((detail.get("payload") or {}).get("body") or "")
    version_before = str((detail.get("payload") or {}).get("version") or "")
    edited = demo.server.put(
        "/api/skills/" + quoted,
        {"instructions": body_before.rstrip() + "\n\n" + EDIT_SUFFIX + "\n", "note": EDIT_NOTE},
    )
    detail_after = demo.server.get("/api/skills/" + quoted)
    body_after = str((detail_after.get("payload") or {}).get("body") or "")
    versions = demo.server.get("/api/skills/" + quoted + "/versions")
    version_list = (versions.get("payload") or {}).get("versions") or []
    # The version to fetch is the one that existed before the edit - not the
    # newest row, which is the edit itself.
    old_version = version_before or (str((version_list[-1] or {}).get("version") or "") if version_list else "")
    old_body_response = demo.server.get("/api/skills/%s/versions/%s" % (quoted, urllib.parse.quote(old_version, safe="")))
    old_body = str((old_body_response.get("payload") or {}).get("body") or "")
    names = [str(entry.get("name")) for entry in (listing.get("payload") or {}).get("skills") or []]
    reset_skill_cache()
    prompt_after_edit = build_prompt_if_available()
    demo.extra["rule_review"] = {
        "listing": {"status": listing.get("status"), "skills": names},
        "detail_before": {"status": detail.get("status"), "version": version_before,
                          "body": gc.clip(body_before, 1200)},
        "edit": {"status": edited.get("status"), "payload": {
            key: edited.get("payload", {}).get(key) for key in ("ok", "changed", "version", "snapshot")
        }},
        "detail_after": {"status": detail_after.get("status"),
                         "version": (detail_after.get("payload") or {}).get("version"),
                         "body": gc.clip(body_after, 1200)},
        "versions": {"status": versions.get("status"), "versions": version_list},
        "old_version_content": {"status": old_body_response.get("status"), "version": old_version,
                                "body": gc.clip(old_body, 1200)},
        "edit_visible_in_prompt": EDIT_SUFFIX in prompt_after_edit,
    }
    edit_ok = (
        bool(listing.get("ok")) and primary in names
        and bool(detail.get("ok")) and bool(body_before.strip())
        and bool(edited.get("ok")) and bool((edited.get("payload") or {}).get("changed"))
        and EDIT_SUFFIX in body_after
        and str((detail_after.get("payload") or {}).get("version")) != version_before
        and bool(old_body.strip()) and EDIT_SUFFIX not in old_body
    )
    report.check(
        "demo.rule_is_reviewable_and_editable_over_http",
        edit_ok,
        detail=demo.extra["rule_review"],
        metrics={"http_calls": 6, "versions_listed": len(version_list)},
        reason="" if edit_ok else "the rule could not be read, edited and re-read through the product API",
    )


def build_prompt_if_available() -> str:
    from mellowday.runtime.prompt import build_system_prompt

    return build_system_prompt()


async def demo_behaviour_steps(demo: Demo, primary: str, quoted: str, probes: tuple[str, ...]) -> None:
    """5-9: the rule changes behaviour, survives repetition, can be overridden,
    is not loaded for unrelated requests, and can be disabled, re-enabled and
    rolled back."""
    report, run = demo.report, demo.run
    from mellowday.runtime.prompt import build_system_prompt
    from mellowday.runtime.skills import disable_skill, enable_skill, reset_skill_cache

    # Probes and expectations are derived from the *current* body (T6 F3): a
    # hard-coded phrase stops matching the moment the rule is reworded.
    bodies_now = demo.rule_texts()
    description_now = next(
        (str(entry.get("description") or "") for entry in demo.skill_entries()
         if str(entry.get("name")) == primary), ""
    )
    body_probe = pick_body_probe(bodies_now.get(primary, ""), description_now)
    rule_probes = tuple(probe for probe in (primary, body_probe, *RULE_FACT_TERMS) if probe)
    demo.extra["probes"] = {"skill": primary, "body_probe": body_probe,
                            "fact_channel_terms": list(RULE_FACT_TERMS)}

    # ------------------------------------------- 5. a new session follows it
    follows = await demo.turn("follow", PLAN_ASK, probes=rule_probes)
    verdict = evaluate_structural_rule(
        follows.get("reply"), event_title=EVENT_TITLE, todos=SEED_TODOS
    )
    follow_calls = demo.calls_for(follows.get("request_seqs"))
    follow_delivery = rule_delivery(follow_calls, rule_name=primary, body_probe=body_probe,
                                    sample=follows)
    delivered = bool(
        follow_delivery["retrieved_block_mentions_rule"]
        or follow_delivery["body_probe_in_payload"]
        or any(tool.get("name") == "skill" for tool in follows.get("tool_calls") or [])
    )
    demo.extra["follow_turn"] = {**follows, "rule": verdict, "delivery": follow_delivery,
                                 "body_probe": body_probe}
    report.check(
        "demo.new_session_follows_the_rule",
        bool(verdict["ok"]) and delivered,
        detail={"sample": follows, "structural_assertions": verdict["detail"],
                "delivery": follow_delivery, "body_probe": body_probe,
                "body_probe_hit": follow_delivery["body_probe_in_payload"]},
        metrics={"assertions_passed": len(verdict["detail"]["assertions"]) - len(verdict["detail"]["failed"]),
                 "of": len(verdict["detail"]["assertions"]),
                 "rule_text_delivered": int(delivered)},
        reason="" if verdict["ok"] else "the new session did not satisfy the learned rule",
    )

    # ------------------------------- 6a. repeated feedback keeps the edit
    repeat = await demo.turn_in_session(follows["session_id"], CORRECTION, approve=True, probes=rule_probes)
    reset_skill_cache()
    entries_after_repeat = demo.skill_entries()
    names_after_repeat = [str(entry.get("name")) for entry in entries_after_repeat]
    bodies_after_repeat = demo.rule_texts()
    body_now = bodies_after_repeat.get(primary, "")
    applied_events = [str(event.get("type")) for event in (repeat.get("learning_events") or [])]
    demo.extra["repeat_feedback"] = {
        "sample": repeat, "skills": names_after_repeat, "events": applied_events,
        "edit_survived": EDIT_SUFFIX in body_now, "body": gc.clip(body_now, 1200),
    }
    report.check(
        "demo.repeated_feedback_keeps_the_edited_rule",
        names_after_repeat.count(primary) == 1
        and sorted(names_after_repeat) == sorted([*demo.baseline_names, primary])
        and EDIT_SUFFIX in body_now,
        detail=demo.extra["repeat_feedback"],
        metrics={"skills": len(names_after_repeat), "new_skills": len(set(names_after_repeat) - set(demo.baseline_names))},
        reason="" if EDIT_SUFFIX in body_now else "the repeated correction dropped the edited sentence",
    )

    # ------------------------------ 6b + 7. temporary request, explicit override
    versions_before_temp = {str(entry.get("name")): str(entry.get("version"))
                            for entry in demo.skill_entries()}
    temp = await demo.turn_in_session(follows["session_id"], TEMP_ASK, approve=True, probes=rule_probes)
    reset_skill_cache()
    entries_after_temp = demo.skill_entries()
    names_after_temp = [str(entry.get("name")) for entry in entries_after_temp]
    versions_after_temp = {str(entry.get("name")): str(entry.get("version"))
                            for entry in entries_after_temp}
    body_after_temp = demo.rule_texts().get(primary, "")
    temp_markers = ("临时", "一句话概括", "不用记住", "列出全部待办")
    temp_derived_lines = [
        line.strip() for line in body_after_temp.splitlines()
        if line.strip() and any(marker in line for marker in temp_markers)
    ]
    applied_in_temp_turn = [
        str(event.get("type")) for event in (temp.get("learning_events") or [])
        if str(event.get("type")) == "skill_candidate_applied"
    ]
    provenance = evolution_tail(run)
    demo.extra["temporary_request"] = {
        "sample": temp, "skills": names_after_temp,
        "versions_before": versions_before_temp, "versions_after": versions_after_temp,
        "one_off_markers": list(temp_markers),
        "body_lines_derived_from_the_one_off_request": temp_derived_lines,
        "skill_candidate_applied_in_this_turn": applied_in_temp_turn,
        "provenance_tail": provenance[-4:],
    }
    versions_unchanged = versions_after_temp == versions_before_temp
    ok_temp = (
        sorted(names_after_temp) == sorted([*demo.baseline_names, primary])
        and not applied_in_temp_turn
        and not temp_derived_lines
        and versions_unchanged
    )
    report.check(
        "demo.temporary_request_is_not_learned",
        ok_temp,
        detail={
            **demo.extra["temporary_request"],
            "note": (
                "a one-off request must not change the durable rule: neither a version bump, "
                "nor a new skill, nor a rule line derived from the one-off wording"
            ),
        },
        metrics={"skills_before": len(demo.baseline_names) + 1, "skills_after": len(names_after_temp),
                 "one_off_rule_lines": len(temp_derived_lines),
                 "versions_unchanged": versions_unchanged},
        reason="" if ok_temp else (
            "the one-off request changed the durable rule (applied=%s, one-off rule lines=%d, "
            "versions %s -> %s)"
            % (applied_in_temp_turn, len(temp_derived_lines), versions_before_temp, versions_after_temp)
        ),
    )

    override = await demo.turn_in_session(follows["session_id"], OVERRIDE_ASK, approve=True, probes=rule_probes)
    override_hits = [title for title in SEED_TODOS if title in str(override.get("reply") or "")]
    demo.extra["override_turn"] = {**override, "todos_listed": override_hits}
    report.check(
        "demo.explicit_request_overrides_the_habit",
        gc.sample_is_valid(override)[0] and len(override_hits) >= 5,
        detail=demo.extra["override_turn"],
        metrics={"todos_listed": len(override_hits), "of": len(SEED_TODOS)},
        reason="" if len(override_hits) >= 5 else "the explicit request did not win over the stored habit",
    )

    # ------------------------------- 8. an unrelated request must not load it
    # Payload-level, two requests of different shapes (t14's counterexample was a
    # single request; t19 changed the retrieval gate, so this row is re-measured
    # here). "Loaded" is judged from the recorded outbound payload, never from the
    # skill list - and the positive control is this same run's rule-retrieval
    # samples (there the <retrieved_skills> block does mention the rule).
    unrelated_samples = []
    for index, ask in enumerate(UNRELATED_ASKS):
        sample = await demo.turn("unrelated", ask, index=index, probes=rule_probes)
        calls = demo.calls_for(sample.get("request_seqs"))
        payloads = [str(call.get("payload_text") or "") for call in calls]
        blocks = [retrieval_block(payload) for payload in payloads]
        sample["retrieval_evidence"] = {
            "ask": ask,
            "retrieved_skills_block_present": any(bool(block) for block in blocks),
            "retrieved_skills_blocks": [gc.clip(block, 300) for block in blocks if block],
            "rule_mentioned_in_retrieved_block": any(primary in block for block in blocks),
            "body_probe_in_payload": bool(body_probe) and any(body_probe in payload for payload in payloads),
            "skill_tool_calls": [tool.get("name") for tool in sample.get("tool_calls") or []
                                 if tool.get("name") == "skill"],
            "rule_text_anywhere_in_payload": any(primary in payload for payload in payloads),
        }
        unrelated_samples.append(sample)
    created = [row for row in gc.db_rows(demo.store, "todos") if "快递" in str(row.get("title") or "")]
    unrelated_assertions = evaluate_structural_rule(
        unrelated_samples[0].get("reply"), event_title=EVENT_TITLE, todos=SEED_TODOS
    )
    loaded_samples = [
        sample for sample in unrelated_samples
        if (sample.get("retrieval_evidence") or {}).get("retrieved_skills_block_present")
        or (sample.get("retrieval_evidence") or {}).get("skill_tool_calls")
        or (sample.get("retrieval_evidence") or {}).get("body_probe_in_payload")
    ]
    demo.extra["unrelated_turns"] = {
        "samples": unrelated_samples,
        "rows_with_快递": len(created),
        "planning_shape_assertions": unrelated_assertions["detail"]["assertions"],
    }
    # The same-run control: a planning request in *this* run must really have
    # loaded the rule, otherwise "the unrelated requests did not" says nothing
    # (retrieval could be broken for everything).  Judged with the same helper as
    # the rows above, over the request payloads *and* the tool results (t23: the
    # runtime hands the rule body over through the skill tool result).
    control_samples = _as_sample_list(demo.extra.get("follow_turn"))
    control_delivery = rule_delivery(
        demo.calls_for((control_samples[0] if control_samples else {}).get("request_seqs")),
        rule_name=primary, body_probe=body_probe,
        sample=control_samples[0] if control_samples else None,
    )
    control_ok = bool(
        control_delivery["retrieved_block_mentions_rule"]
        or control_delivery["body_probe_in_payload"]
        or control_delivery["body_probe_in_tool_results"]
        or control_delivery["skill_tool_call_present"]
    )
    control_detail = {
        "session_id": (control_samples[0] if control_samples else {}).get("session_id"),
        "ask": (control_samples[0] if control_samples else {}).get("message"),
        **{key: control_delivery[key] for key in (
            "retrieved_block_mentions_rule", "body_probe_in_payload",
            "body_probe_in_tool_results", "skill_tool_call_present",
            "system_prompt_advertises_rule")},
        "note": (
            "a planning request from the same run: the rule must be loadable here, "
            "otherwise the absence of rule text in the unrelated requests is not evidence"
        ),
    }
    report.check(
        "demo.planning_request_in_this_run_can_load_the_rule",
        control_ok,
        detail=control_detail,
        metrics={"retrieved_block_mentions_rule": int(bool(control_delivery["retrieved_block_mentions_rule"])),
                 "body_probe_in_payload": int(bool(control_delivery["body_probe_in_payload"])),
                 "body_probe_in_tool_results": int(bool(control_delivery["body_probe_in_tool_results"])),
                 "skill_tool_call_present": int(bool(control_delivery["skill_tool_call_present"]))},
        reason="" if control_ok else (
            "no planning request in this run loaded the rule, so the unrelated-request "
            "absence of rule text cannot be attributed to relevance"
        ),
    )
    row7_detail = {**demo.extra["unrelated_turns"], "positive_control_from_the_same_run": control_detail}
    row7_metrics = {"samples": len(unrelated_samples), "samples_that_loaded_a_skill": len(loaded_samples),
                    "rows_created": len(created)}
    row7_ok = (
        all(gc.sample_is_valid(sample)[0] for sample in unrelated_samples)
        and not loaded_samples and len(created) == 1
        and not unrelated_assertions["ok"]
    )
    if not control_ok:
        report.inconclusive(
            "demo.unrelated_request_does_not_load_the_rule (sampled %d)" % len(unrelated_samples),
            "the same-run control did not load the rule, so 'unrelated requests do not load it' "
            "would not distinguish relevance from a broken retrieval path",
            detail=row7_detail, metrics=row7_metrics,
        )
    else:
        report.check(
            "demo.unrelated_request_does_not_load_the_rule (sampled %d)" % len(unrelated_samples),
            row7_ok,
            detail=row7_detail,
            metrics=row7_metrics,
            reason="" if row7_ok else (
                "an unrelated request still carried a retrieved-skills block, a skill tool call or "
                "rule-body text in its payload"
            ),
        )

    # ------------------------------------------- 9. disable / enable / rollback
    controls = {"after_learning_hit": bool(verdict["ok"])}
    disabled = disable_skill(primary)
    reset_skill_cache()
    prompt_disabled = build_system_prompt()
    off_samples = await gc.sample_sessions(
        demo.registry, run, "off", PLAN_ASK, demo.attempts,
        recorder=demo.recorder, payload_probes=[probe for probe in (primary, body_probe) if probe],
    )
    # The leak judgement is the gate's three-segment classifier (N5): the old
    # probe only looked for the skill name and a body snippet, so a rule arriving
    # through the recalled-facts block was reported as "no leak" (T18/T20 caught
    # that false negative with the payload in hand). One implementation, reused.
    probe_set = []
    for probe in (primary, body_probe, *RULE_FACT_TERMS):
        if probe and probe not in probe_set:
            probe_set.append(probe)
    for sample in off_samples:
        calls = demo.calls_for(sample.get("request_seqs"))
        sample["delivery"] = rule_delivery(calls, rule_name=primary, body_probe=body_probe,
                                            sample=sample)
        sample["probe_locations"] = gc.payload_probe_locations(calls, probe_set)
        sample["channels"] = gc.payload_channel_evidence(
            calls, [probe for probe in (primary, body_probe) if probe],
            fact_probes=RULE_FACT_TERMS,
        )
        sample["structural"] = evaluate_structural_rule(
            sample.get("reply"), event_title=EVENT_TITLE, todos=SEED_TODOS
        )
        sample["hit"] = bool(sample["structural"]["ok"])
    payload_carriers = [
        sample for sample in off_samples
        if (sample.get("probe_locations") or {}).get("present_anywhere")
    ]
    fact_carriers = [
        sample for sample in off_samples
        if (sample.get("probe_locations") or {}).get("in_recalled_facts_block")
    ]
    superseded_carriers = [
        sample for sample in off_samples
        if (sample.get("probe_locations") or {}).get("in_superseded_block")
    ]
    skill_leaks = [
        sample for sample in off_samples
        if (sample.get("probe_locations") or {}).get("elsewhere_in_request")
        or (sample.get("delivery") or {}).get("retrieved_block_mentions_rule")
        or any(tool.get("name") == "skill" for tool in sample.get("tool_calls") or [])
    ]
    prompt_gone = primary not in prompt_disabled
    demo.extra["disable"] = {
        "disable_result": {key: disabled.get(key) for key in ("ok", "changed", "archived_to")},
        "prompt_lacks_rule": prompt_gone,
        "probe_set": probe_set,
        "samples": off_samples,
        "historical_pre_t9_observations": list(PRIOR_FACT_CHANNEL_OBSERVATIONS),
    }
    report.check(
        "demo.disabled_rule_leaves_prompt_and_skill_channel",
        bool(disabled.get("ok")) and prompt_gone and not skill_leaks,
        detail=demo.extra["disable"],
        metrics={"samples": len(off_samples), "skill_channel_samples": len(skill_leaks)},
        reason="" if (prompt_gone and not skill_leaks) else "the disabled rule still reached the model through the skill channel",
    )
    report.check(
        "demo.disabled_rule_leaves_no_rule_text_in_the_payload (sampled %d)" % len(off_samples),
        not payload_carriers and all(
            (sample.get("probe_locations") or {}).get("requests_scanned") for sample in off_samples
        ),
        detail={
            "probes": probe_set,
            "segments_checked": ["recalled-facts block", "superseded-values block", "rest of the request"],
            "samples_carrying_rule_text": [
                {"session_id": sample.get("session_id"),
                 "locations": sample.get("probe_locations")}
                for sample in payload_carriers
            ],
            "per_sample_locations": [
                {"session_id": sample.get("session_id"),
                 "locations": sample.get("probe_locations")}
                for sample in off_samples
            ],
            "note": (
                "this is the N5-corrected judgement: the old probe only looked for the skill "
                "name and a body snippet, so a rule delivered through the recalled-facts block "
                "scored payload_leaks=0 (T18/T20). The classifier is gate_common's, shared with "
                "the learning gate."
            ),
        },
        metrics={"samples": len(off_samples), "samples_carrying_rule_text": len(payload_carriers),
                 "via_recalled_facts": len(fact_carriers), "via_superseded_values": len(superseded_carriers)},
        reason="" if not payload_carriers else (
            "the disabled rule still reached the model through the request payload"
        ),
    )
    ok_off, detail_off = gc.off_side_verdict(off_samples, control_ok=controls["after_learning_hit"])
    # I24's disable-side criterion, judged on the recorded payload (three segments,
    # both channels) *and* on the behaviour: a disabled habit that is still being
    # delivered cannot count as stopped, no matter what the skill list says.
    ok_behaviour = bool(ok_off) and not payload_carriers
    behaviour_reason = detail_off.get("inconclusive_reason", "") or detail_off.get("reason", "")
    if payload_carriers:
        behaviour_reason = (
            "the disabled rule still reached the model in %d of %d requests "
            "(recalled-facts %d, superseded-values %d, skill channel %d); a rule that is "
            "still delivered cannot count as stopped"
            % (len(payload_carriers), len(off_samples), len(fact_carriers),
               len(superseded_carriers), len(skill_leaks))
        )
    report.check(
        "demo.disabled_rule_stops_changing_behaviour (sampled %d)" % len(off_samples),
        ok_behaviour,
        detail={
            "verdict": detail_off,
            "payload_carriers": len(payload_carriers),
            "via_recalled_facts": len(fact_carriers),
            "via_superseded_values": len(superseded_carriers),
            "skill_channel_carriers": len(skill_leaks),
            "rule_facts_in_the_fact_store_this_run": demo.extra["fact_channel_after_correction"],
            "historical_pre_t9_observations": list(PRIOR_FACT_CHANNEL_OBSERVATIONS),
            "note": (
                "historical_pre_t9_observations records why this condition used to be "
                "reported as blocked; they are history, not part of this run's verdict"
            ),
            "samples": off_samples,
        },
        metrics={"hits": detail_off["hits"], "of": detail_off["of"], "valid": detail_off["valid"],
                 "payload_carriers": len(payload_carriers),
                 "via_recalled_facts": len(fact_carriers)},
        reason=behaviour_reason,
    )

    enabled = enable_skill(primary)
    reset_skill_cache()
    prompt_enabled = build_system_prompt()
    back_samples = await gc.sample_sessions(
        demo.registry, run, "back", PLAN_ASK, demo.attempts,
        recorder=demo.recorder, payload_probes=[probe for probe in (primary, body_probe) if probe],
    )
    for sample in back_samples:
        calls = demo.calls_for(sample.get("request_seqs"))
        sample["delivery"] = rule_delivery(calls, rule_name=primary, body_probe=body_probe,
                                            sample=sample)
        sample["structural"] = evaluate_structural_rule(
            sample.get("reply"), event_title=EVENT_TITLE, todos=SEED_TODOS
        )
        sample["hit"] = bool(sample["structural"]["ok"])
    ok_back, detail_back = gc.on_side_verdict(back_samples, min_hits=1)
    demo.extra["enable"] = {
        "enable_result": {key: enabled.get(key) for key in ("ok", "changed")},
        "prompt_has_rule": primary in prompt_enabled, "samples": back_samples,
    }
    report.check(
        "demo.enabled_rule_changes_behaviour_again",
        bool(enabled.get("ok")) and primary in prompt_enabled and ok_back,
        detail=demo.extra["enable"],
        metrics={"hits": detail_back["hits"], "of": detail_back["of"], "valid": detail_back["valid"]},
        reason=detail_back.get("inconclusive_reason", "") or detail_back.get("reason", ""),
    )

    # -------------------------------------------------- version rollback
    versions = demo.server.get("/api/skills/" + quoted + "/versions")
    version_rows = (versions.get("payload") or {}).get("versions") or []
    first_version = str(version_rows[-1].get("version")) if version_rows else ""
    before_rollback = demo.rule_texts().get(primary, "")
    rolled = demo.server.post("/api/skills/%s/versions/%s/restore" % (quoted, urllib.parse.quote(first_version, safe="")))
    reset_skill_cache()
    after_rollback = demo.rule_texts().get(primary, "")
    rollback_detail = demo.server.get("/api/skills/" + quoted)
    demo.extra["rollback"] = {
        "versions": {"status": versions.get("status"), "rows": version_rows},
        "restore": {"status": rolled.get("status"), "payload": rolled.get("payload")},
        "body_before": gc.clip(before_rollback, 900),
        "body_after": gc.clip(after_rollback, 900),
        "detail_after": {"status": rollback_detail.get("status"),
                         "version": (rollback_detail.get("payload") or {}).get("version")},
    }
    report.check(
        "demo.version_rollback_restores_the_earlier_body",
        bool(rolled.get("ok")) and EDIT_SUFFIX not in after_rollback
        and "固定日程" in after_rollback and bool(before_rollback.strip()),
        detail=demo.extra["rollback"],
        metrics={"versions": len(version_rows), "first_version": first_version},
        reason="" if rolled.get("ok") else "the version restore did not succeed",
    )


async def demo_folding_and_restart(demo: Demo, probes: tuple[str, ...]) -> None:
    """10. fold a long conversation, then continue it in a new process."""
    report, run = demo.report, demo.run
    from mellowday.runtime import sessions as session_store
    from mellowday.runtime.skills import reset_skill_cache  # F1: was missing here

    skills_before_folding = [str(entry.get("name")) for entry in demo.skill_entries()]
    session_id = run.session_id("long", 0)
    first = await demo.turn_in_session(session_id, FOLD_TURN_1, probes=probes)
    second = await demo.turn_in_session(session_id, FOLD_TURN_2, probes=probes)
    agent = demo.registry.get(session_id).agent
    messages_before = len(getattr(agent, "_openai_messages", []) or [])
    folded_memory: list[dict] = []
    fold_error = ""
    try:
        await agent.compact()
    except Exception as exc:
        fold_error = "%s: %s" % (type(exc).__name__, exc)
    messages_after = len(getattr(agent, "_openai_messages", []) or [])
    folded_memory = list(getattr(agent, "_folded_session_memories", []) or [])
    folded_text = json.dumps(folded_memory, ensure_ascii=False, default=str)
    third = await demo.turn_in_session(session_id, FOLD_TURN_3, probes=probes)
    rows_for_task = [row for row in gc.db_rows(demo.store, "todos")
                     if str(row.get("title") or "") == TASK_TITLE]
    demo.extra["folding"] = {
        "session_id": session_id,
        "first_turn": first, "second_turn": second, "third_turn": third,
        "messages_before_fold": messages_before,
        "messages_after_fold": messages_after,
        "folded_memories": len(folded_memory),
        "folded_text": gc.clip(folded_text, 2000),
        "fold_error": fold_error,
        "task_rows": len(rows_for_task),
    }
    report.check(
        "demo.folding_replaces_history_with_folded_memory",
        messages_after < messages_before and bool(folded_memory) and not fold_error
        and TASK_TITLE in folded_text,
        detail=demo.extra["folding"],
        metrics={"messages_before": messages_before, "messages_after": messages_after,
                 "folded_memories": len(folded_memory)},
        reason=fold_error or ("" if messages_after < messages_before else "the history was not folded"),
    )
    continued = TASK_TITLE in str(third.get("reply") or "") or "第三条" in str(third.get("reply") or "")
    report.check(
        "demo.session_continues_after_folding",
        gc.sample_is_valid(third)[0] and continued and len(rows_for_task) == 1,
        detail={"sample": third, "task_rows": len(rows_for_task),
                "folded_text": gc.clip(folded_text, 800)},
        metrics={"task_rows": len(rows_for_task), "reply_chars": len(str(third.get("reply") or ""))},
        reason="" if continued else "the folded session did not continue the unfinished task",
    )

    reset_skill_cache()
    entries_after_folding = demo.skill_entries()
    names_after_folding = [str(entry.get("name")) for entry in entries_after_folding]
    new_skills_from_folding = [name for name in names_after_folding if name not in skills_before_folding]
    folding_bodies = demo.rule_texts()
    folding_derived = [
        name for name in new_skills_from_folding
        if any(marker in folding_bodies.get(name, "") for marker in ("第二条", "数据口径", "展开一点"))
    ]
    demo.extra["folding_learning_side_effects"] = {
        "skills_before": skills_before_folding,
        "skills_after": names_after_folding,
        "new_skills": new_skills_from_folding,
        "new_skills_quoting_a_one_off_instruction": folding_derived,
    }
    report.check(
        "demo.one_off_instructions_do_not_create_skills",
        not new_skills_from_folding,
        detail=demo.extra["folding_learning_side_effects"],
        metrics={"new_skills": len(new_skills_from_folding),
                 "quoting_a_one_off": len(folding_derived)},
        reason="" if not new_skills_from_folding else (
            "a one-off task instruction during the folding conversation became a durable skill: %s"
            % ", ".join(new_skills_from_folding)
        ),
    )

    child_out = run.artifacts_dir / "restart-phase.json"
    child = ds.run_child(
        Path(__file__).resolve(),
        ["--phase", "continue", "--run-dir", str(run.root), "--session", session_id,
         "--out", str(child_out)],
        run.data_dir,
        log_path=run.artifacts_dir / "restart-phase.log",
    )
    child_result = ds.read_json(child_out)
    demo.extra["restart"] = {"child": child, "result": child_result}
    ok_restart = (
        child.get("exit_code") == 0
        and bool(child_result.get("task_title_in_restored_state"))
        and int(child_result.get("restored_message_count") or 0) > 0
        and TASK_TITLE in str(child_result.get("reply") or "")
    )
    report.check(
        "demo.session_continues_after_restart",
        ok_restart,
        detail=demo.extra["restart"],
        metrics={"restored_messages": child_result.get("restored_message_count"),
                 "reply_chars": len(str(child_result.get("reply") or ""))},
        reason="" if ok_restart else "the restarted process could not continue the unfinished task",
    )


def evolution_tail(run: gc.RunContext, limit: int = 6) -> list[dict]:
    from mellowday import paths

    out: list[dict] = []
    base = paths.evolution_dir()
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.jsonl")):
        try:
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            continue
        for line in lines[-limit:]:
            out.append({"file": path.name, "entry": gc.clip(line, 900)})
    return out[-limit:]


# -------------------------------------------------------------------- main


async def main() -> int:
    args = parse_args()

    # Negative controls are a mode of their own: they need no model, no seed and
    # no network, and they must be runnable on their own so a reviewer can check
    # the judgement itself (python scripts/demo_core.py --selfcheck).
    if args.selfcheck:
        run = gc.RunContext(
            GATE + "-selfcheck", run_root=args.run_root, run_id=args.run_id, keep=args.keep,
            source_data_dir=args.source_data_dir or None,
        ).prepare()
        report = gc.Report(GATE + "-selfcheck", run)
        gc.ensure_src_on_path()
        print("selfcheck: " + run.run_id)
        run_selfcheck(report)
        report_path = Path(args.json_out) if args.json_out else run.artifacts_dir / "selfcheck-report.json"
        payload = report.write(
            report_path,
            l3={"status": "not_run", "reason": "selfcheck only", "model": "", "api_base": ""},
            extra={"controls": len(report.checks),
                   "note": "negative controls for the structural judgement and the shared predicates"},
        )
        counts = payload["summary"]
        print("")
        print("result: %d passed, %d failed, %d inconclusive, %d pending (of %d)" % (
            counts["passed"], counts["failed"], counts["inconclusive"], counts["pending"], counts["total"]))
        print("report: " + str(report_path))
        return report.exit_code()

    attempts = max(1, int(args.attempts))

    run = gc.RunContext(
        GATE, run_root=args.run_root, run_id=args.run_id, keep=args.keep,
        source_data_dir=args.source_data_dir or None,
    ).prepare()
    report = gc.Report(GATE, run)
    demo = Demo(run, report, attempts=attempts)
    gc.ensure_src_on_path()

    print("run:  " + run.run_id)
    print("data: " + str(run.data_dir))
    print("real: " + str(run.source_data_dir) + "  (never written to)")

    initial = run.isolated_state()
    report.check(
        "demo.run_directory_starts_empty",
        not initial["sessions"] and not initial["skills"] and not initial["has_database"],
        detail=initial,
    )
    seeded = run.seed_model_config()
    print("model: %s  endpoint: %s  key: %s" % (
        seeded["model"], seeded["api_base"],
        "present(" + seeded["api_key_fingerprint"] + ")" if seeded["api_key_present"] else "absent",
    ))

    from mellowday.storage.store import Store
    from mellowday.web_app.service import SessionRegistry

    demo.store = Store(data_dir=run.data_dir)
    demo.registry = SessionRegistry(store=demo.store)

    await run_offline_steps(demo)
    demo.baseline_names = [str(entry.get("name")) for entry in demo.skill_entries()]

    status = {"status": "not_run", "reason": "", "model": seeded["model"], "api_base": seeded["api_base"]}
    if args.offline or not seeded["api_key_present"]:
        status["reason"] = "offline mode requested" if args.offline else "no credential available"
        for name in (
            "demo.planner_reads_real_records_and_current_facts",
            "demo.correction_is_confirmed_and_learned",
            "demo.correction_does_not_duplicate_the_rule_into_the_fact_store",
            "demo.rule_is_reviewable_and_editable_over_http",
            "demo.new_session_follows_the_rule",
            "demo.repeated_feedback_keeps_the_edited_rule",
            "demo.temporary_request_is_not_learned",
            "demo.explicit_request_overrides_the_habit",
            "demo.unrelated_request_does_not_load_the_rule (sampled %d)"
            % len(UNRELATED_ASKS),
            "demo.disabled_rule_leaves_prompt_and_skill_channel",
            "demo.disabled_rule_leaves_no_rule_text_in_the_payload (sampled %d)" % attempts,
            "demo.disabled_rule_stops_changing_behaviour (sampled %d)" % attempts,
            "demo.enabled_rule_changes_behaviour_again",
            "demo.version_rollback_restores_the_earlier_body",
            "demo.folding_replaces_history_with_folded_memory",
            "demo.session_continues_after_folding",
            "demo.session_continues_after_restart",
        ):
            report.pending(name, status["reason"])
    else:
        demo.recorder.install()
        endpoint = gc.probe_endpoint(seeded["api_base"], run.credentials.get("api_key", ""))
        demo.extra["endpoint"] = endpoint
        if not endpoint["ok"]:
            status["reason"] = "endpoint unreachable: %s" % endpoint.get("error")
            for name in (
                "demo.planner_reads_real_records_and_current_facts",
                "demo.correction_is_confirmed_and_learned",
            ):
                report.pending(name, status["reason"])
        else:
            status["status"] = "run"
            demo.server = ds.RealServer(run.data_dir, log_path=run.artifacts_dir / "webapp.log").start()
            demo.extra["web_app_process"] = {"base": demo.server.base, "startup": demo.server.startup,
                                            "log": str(demo.server.log_path)}
            try:
                await run_l3_steps(demo)
            except Exception as exc:
                import traceback

                status["runner_exception"] = "%s: %s" % (type(exc).__name__, exc)
                report.check(
                    "demo.runner_completed_without_an_exception", False,
                    detail={"exception": status["runner_exception"],
                            "traceback": gc.clip(traceback.format_exc(), 2500)},
                    reason=status["runner_exception"],
                )
            finally:
                demo.extra["web_app_process"]["stop"] = demo.server.stop()

    raw_path = run.artifacts_dir / "model-calls.jsonl"
    demo.recorder.dump_raw(raw_path)
    pollution = run.pollution_report()
    report.check(
        "demo.real_data_directory_untouched",
        pollution["clean"],
        detail=pollution,
        reason="" if pollution["clean"] else "the demonstration changed the machine's real data directory",
    )

    l3_summary = {
        **status,
        "requests": len(demo.recorder.calls),
        "recorder_available": demo.recorder.available,
        "recorder_errors": demo.recorder.install_errors,
        "raw_requests": str(raw_path),
    }
    extra = {
        **demo.extra,
        "limitations_and_history": [
            "The disable-side judgement is now measured on the request payload in three segments "
            "(recalled-facts block / superseded-values block / rest of the request). Before t23 it "
            "only looked for the skill name and a body snippet, so a rule delivered through the "
            "recalled-facts block scored payload_leaks=0 - the false negative T18 and T20 caught "
            "with the payload in hand.",
            "History (kept for traceability, not part of this run's verdict): before t9 the same "
            "correction could be written both as a skill and as a user fact, and the fact was "
            "injected into every session - which is why this condition used to be reported as "
            "blocked rather than passed.",
            "The comparison arms in evals/p5_compare.py run one OS process each: the skills "
            "package caches discovery in a process-global, so arms sharing a process could see "
            "each other's skills (found by the T6 review).",
        ],
        "requests": demo.recorder.report_view(),
        "model_calls": demo.recorder.model_sequence(),
        "database_after": gc.db_view(demo.store),
        "artifacts": {"raw_requests": str(raw_path),
                      "workspace_fingerprint": str(run.artifacts_dir / "workspace-fingerprint.json")},
    }
    # An offline check must not overwrite the stable demonstration evidence.
    demo_report_path = Path(args.json_out) if args.json_out else (
        REPORT_PATH if l3_summary["status"] == "run" else run.artifacts_dir / REPORT_PATH.name
    )
    payload = report.write(demo_report_path, l3=l3_summary, extra=extra)
    counts = payload["summary"]
    print("")
    print("result: %d passed, %d failed, %d inconclusive, %d pending (of %d)" % (
        counts["passed"], counts["failed"], counts["inconclusive"], counts["pending"], counts["total"]))
    print("l3:     %s %s" % (l3_summary["status"], l3_summary.get("reason", "")))
    print("report: " + str(demo_report_path))
    print("raw:    " + str(raw_path))
    return report.exit_code()


if __name__ == "__main__":
    _args = parse_args()
    if _args.phase == "continue":
        raise SystemExit(continue_phase(_args))
    raise SystemExit(asyncio.run(main()))
