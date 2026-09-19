"""Narrow calendar tools for the existing assistant execution dispatcher."""
import json
from mellowday.personal_assistant.schedule import ScheduleService


def tool_definitions() -> list[dict]:
    string = {"type": "string"}
    event = {key: string for key in ("title", "detail", "start_at", "end_at", "timezone", "status")}
    event.update(all_day={"type": "boolean"}, recurrence={"type": "string", "enum": ["none", "daily", "weekly", "weekdays"]}, reminder_minutes={"type": ["integer", "null"], "minimum": 0})
    scope = {"event_id": string, "scope": {"type": "string", "enum": ["single", "series"]}, "occurrence_start": string}
    subscription = {key: string for key in ("title", "time", "timezone", "session_id")}
    subscription.update(recurrence={"type": "string", "enum": ["daily", "weekly", "weekdays"]}, enabled={"type": "boolean"}, weekday={"type": "integer", "minimum": 0, "maximum": 6, "description": "周一为 0，周日为 6"})
    entries = [
        ("calendar_open", "打开日历侧栏，可定位某个日程。", {"event_id": string}, []),
        ("calendar_events", "按起止区间查询真实日程（包含重复实例）。", {"start": string, "end": string}, ["start", "end"]),
        ("calendar_event_create", "建立区间日程和明确提醒。时间须包含时区或指定 timezone。", event, ["title", "start_at", "end_at"]),
        ("calendar_event_update", "修改日程，重复事项须明确仅本次或整个系列。", {**event, **scope}, ["event_id"]),
        ("calendar_event_cancel", "取消日程或其单次实例。", scope, ["event_id"]),
        ("calendar_subscriptions", "查看用户主动订阅的定时日程汇报。", {}, []),
        ("calendar_subscription_create", "仅在用户明确要求订阅时建立定时日程汇报；默认送达当前聊天。time 为 HH:MM。", subscription, ["title", "time"]),
        ("calendar_subscription_update", "修改或暂停已有订阅。", {**subscription, "subscription_id": string}, ["subscription_id"]),
        ("calendar_subscription_delete", "取消已有定时汇报订阅。", {"subscription_id": string}, ["subscription_id"]),
    ]
    return [{"name": name, "description": desc, "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False}} for name, desc, props, required in entries]


async def execute_tool(service: ScheduleService, name: str, arguments: dict, *, session_id: str | None = None, emit=None) -> str:
    args = dict(arguments)
    try:
        if name == "calendar_open":
            result = {"ok": True, "event_id": args.get("event_id")}
            if emit:
                emit({"type": "calendar_open", **result})
        elif name == "calendar_events":
            result = {"events": service.calendar.events(args["start"], args["end"])}
        elif name == "calendar_event_create":
            result = {"event": service.calendar.create(args)}
        elif name in {"calendar_event_update", "calendar_event_cancel"}:
            event_id = args.pop("event_id")
            scope, occurrence = args.pop("scope", "series"), args.pop("occurrence_start", None)
            result = {"event": service.calendar.update(event_id, {"status": "cancelled"} if name.endswith("cancel") else args, scope=scope, occurrence_start=occurrence)}
        elif name == "calendar_subscriptions":
            result = {"subscriptions": service.subscriptions()}
        elif name == "calendar_subscription_create":
            args.setdefault("session_id", session_id)
            result = {"subscription": service.save_subscription(args)}
        elif name == "calendar_subscription_update":
            result = {"subscription": service.save_subscription(args, args.pop("subscription_id"))}
        elif name == "calendar_subscription_delete":
            service.delete_subscription(args["subscription_id"])
            result = {"ok": True}
        else:
            return json.dumps({"ok": False, "error": "unknown_tool"})
        return json.dumps(result, ensure_ascii=False)
    except (KeyError, ValueError, TypeError) as exc:
        return json.dumps({"ok": False, "error": "calendar_error", "message": str(exc)}, ensure_ascii=False)
