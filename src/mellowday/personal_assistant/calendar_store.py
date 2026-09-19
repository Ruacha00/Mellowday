"""Calendar intervals over the existing record store; no duplicate legacy data."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mellowday.storage.store import Store, DONE_STATUSES

UTC = timezone.utc
RECURRENCES = {"none", "daily", "weekly", "weekdays"}
FIELDS = {"title", "detail", "start_at", "end_at", "all_day", "timezone", "recurrence", "reminder_minutes", "status"}


def moment(value: str | datetime, zone: str = "Asia/Shanghai") -> datetime:
    try:
        tz = ZoneInfo(zone)
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
            # Reject nonexistent local wall times instead of silently moving an event.
            if parsed.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != parsed.replace(tzinfo=None):
                raise ValueError("该时区的本地时间不存在")
        return parsed.astimezone(UTC)
    except (AttributeError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("时间或时区无效") from exc


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def validate(payload: dict, base: dict | None = None) -> dict:
    if set(payload) - FIELDS:
        raise ValueError("包含未知日历字段")
    data = {"detail": "", "all_day": False, "timezone": "Asia/Shanghai", "recurrence": "none", "reminder_minutes": None, "status": "scheduled", **(base or {}), **payload}
    for key in ("title", "detail"):
        if not isinstance(data.get(key), str) or len(data[key]) > (500 if key == "title" else 20000):
            raise ValueError(f"{key} 必须是有效文本")
    if not data["title"].strip():
        raise ValueError("标题不能为空")
    if type(data["all_day"]) is not bool:
        raise ValueError("all_day 必须为布尔值")
    try:
        ZoneInfo(data["timezone"])
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("时区无效") from exc
    if data["recurrence"] not in RECURRENCES:
        raise ValueError("重复规则无效")
    if data["status"] not in {"scheduled", "cancelled", "done"}:
        raise ValueError("日程状态无效")
    reminder = data["reminder_minutes"]
    if reminder is not None and (type(reminder) is not int or not 0 <= reminder <= 525600):
        raise ValueError("提醒提前分钟数必须介于 0 和 525600")
    start = moment(data.get("start_at"), data["timezone"])
    end = moment(data.get("end_at"), data["timezone"])
    if end <= start or end - start > timedelta(days=366):
        raise ValueError("结束时间必须晚于开始时间，且区间不超过 366 天")
    data.update(start_at=iso(start), end_at=iso(end))
    return {key: data[key] for key in FIELDS}


class CalendarStore:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calendar_exceptions (event_id TEXT NOT NULL, occurrence_start TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(event_id, occurrence_start))")

    def _record(self, event_id: str) -> dict:
        for kind in ("calendar", "reminders"):
            record = self.store.get_record(kind, event_id)
            if record:
                return record
        raise KeyError(event_id)

    @staticmethod
    def from_record(record: dict) -> dict | None:
        if not record.get("due_at"):
            return None
        meta = record.get("meta", {}).get("calendar", {})
        if not isinstance(meta, dict):
            meta = {}
        start = moment(record["due_at"])
        # due_at remains canonical so existing chat tools and undo remain effective.
        duration = meta.get("duration_seconds", 3600 if record["kind"] == "calendar" else 60)
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 366 * 86400:
            duration = 3600
        zone = meta.get("timezone", "Asia/Shanghai")
        try:
            ZoneInfo(zone)
        except (TypeError, ZoneInfoNotFoundError):
            zone = "Asia/Shanghai"
        recurrence = meta.get("recurrence", "none")
        if not isinstance(recurrence, str) or recurrence not in RECURRENCES:
            recurrence = "none"
        lead = meta.get("reminder_minutes", 0 if record["kind"] == "reminders" else None)
        if lead is not None and (type(lead) is not int or not 0 <= lead <= 525600):
            lead = None
        return {"id": record["id"], "kind": record["kind"], "title": record.get("title") or "未命名日程", "detail": record.get("detail") or "", "start_at": iso(start), "end_at": iso(start + timedelta(seconds=duration)), "all_day": meta.get("all_day") is True, "timezone": zone, "recurrence": recurrence, "reminder_minutes": lead, "status": record["status"], "created_at": record["created_at"], "updated_at": record["updated_at"]}

    def get(self, event_id: str) -> dict:
        event = self.from_record(self._record(event_id))
        if not event:
            raise ValueError("此记录尚未设置时间")
        return event

    def series(self) -> list[dict]:
        result = []
        for kind in ("calendar", "reminders"):
            for record in self.store.list_records(kind, include_done=False):
                try:
                    event = self.from_record(record)
                    if event:
                        result.append(event)
                except (ValueError, TypeError):
                    continue  # A malformed legacy date must not hide valid events.
        return result

    def _data(self, data: dict, meta: dict | None = None) -> dict:
        return {"title": data["title"], "detail": data["detail"], "due_at": data["start_at"], "status": data["status"], "meta": {**(meta or {}), "calendar": {"duration_seconds": (moment(data["end_at"]) - moment(data["start_at"])).total_seconds(), **{k: data[k] for k in ("all_day", "timezone", "recurrence", "reminder_minutes")}}}}

    def create(self, payload: dict) -> dict:
        row = self.store.create_record("calendar", self._data(validate(payload)))
        return {**self.get(row["id"]), "operation_id": row["operation_id"]}

    def update(self, event_id: str, payload: dict, *, scope: str = "series", occurrence_start: str | None = None) -> dict:
        record = self._record(event_id)
        event = self.get(event_id)
        if scope not in {"single", "series"}:
            raise ValueError("scope 必须是 single 或 series")
        if scope == "single":
            if not occurrence_start:
                raise ValueError("单次修改需要 occurrence_start")
            original = iso(moment(occurrence_start))
            occurrence = self.occurrence(event, moment(original))
            if occurrence is None:
                raise ValueError("该重复实例不存在")
            with self.store._connect() as db:
                prior = db.execute("SELECT payload FROM calendar_exceptions WHERE event_id=? AND occurrence_start=?", (event_id, original)).fetchone()
            if prior:
                occurrence.update(json.loads(prior[0]))
            updated = validate(payload, occurrence)
            # Recurrence belongs to the series and cannot be changed by an exception.
            updated["recurrence"] = event["recurrence"]
            with self.store._connect() as db:
                db.execute("INSERT OR REPLACE INTO calendar_exceptions VALUES (?, ?, ?)", (event_id, original, json.dumps(updated, ensure_ascii=False)))
            return {**event, **updated, "occurrence_start": original}
        updated = validate(payload, event)
        row = self.store.update_record(record["kind"], event_id, self._data(updated, record.get("meta")))
        # Retain exceptions so the standard record undo can restore the old
        # series; expansion ignores exceptions no longer belonging to its anchor.
        return {**self.get(event_id), "operation_id": row["operation_id"]}

    def delete(self, event_id: str, **kwargs) -> dict:
        return self.update(event_id, {"status": "cancelled"}, **kwargs)

    def occurrence(self, event: dict, at: datetime) -> dict | None:
        start = moment(event["start_at"])
        local = at.astimezone(ZoneInfo(event["timezone"]))
        anchor = start.astimezone(ZoneInfo(event["timezone"]))
        days = (local.date() - anchor.date()).days
        recurrence = event["recurrence"]
        if days < 0 or local.timetz().replace(tzinfo=None) != anchor.timetz().replace(tzinfo=None):
            return None
        if recurrence == "none" and at != start or recurrence == "weekly" and days % 7 or recurrence == "weekdays" and local.weekday() >= 5:
            return None
        wall_duration = moment(event["end_at"]).astimezone(ZoneInfo(event["timezone"])).replace(tzinfo=None) - anchor.replace(tzinfo=None)
        end = local + wall_duration
        return {**event, "start_at": iso(at), "end_at": iso(end), "occurrence_start": iso(at)}

    def expand(self, event: dict, start: datetime, end: datetime) -> list[dict]:
        zone = ZoneInfo(event["timezone"])
        anchor = moment(event["start_at"]).astimezone(zone)
        duration = moment(event["end_at"]) - moment(event["start_at"])
        first_day = max(anchor.date(), (start - duration).astimezone(zone).date())
        last_day = end.astimezone(zone).date()
        with self.store._connect() as db:
            exceptions = {row[0]: json.loads(row[1]) for row in db.execute("SELECT occurrence_start,payload FROM calendar_exceptions WHERE event_id=?", (event["id"],))}
        result = []
        if event["recurrence"] == "none":
            days = [anchor.date()]
        else:
            days = (first_day + timedelta(days=i) for i in range(max(0, (last_day - first_day).days + 1)))
        seen = set()
        for day in days:
            local = datetime.combine(day, anchor.timetz().replace(tzinfo=None), tzinfo=zone)
            at = local.astimezone(UTC)
            if at.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue  # Skip a nonexistent recurrence time at the DST spring gap.
            occurrence = self.occurrence(event, at)
            if occurrence:
                key = occurrence["occurrence_start"]
                seen.add(key)
                occurrence.update(exceptions.get(key, {}))
                if occurrence["status"] not in DONE_STATUSES[event["kind"]] and moment(occurrence["start_at"]) < end and moment(occurrence["end_at"]) > start:
                    result.append(occurrence)
        # Moved instances may enter this range from an original date outside it.
        for key, patch in exceptions.items():
            if key not in seen and self.occurrence(event, moment(key)) is not None and patch["status"] == "scheduled" and moment(patch["start_at"]) < end and moment(patch["end_at"]) > start:
                result.append({**event, **patch, "occurrence_start": key})
        return result

    def events(self, start: str | datetime, end: str | datetime) -> list[dict]:
        low, high = moment(start), moment(end)
        if high <= low or high - low > timedelta(days=3660):
            raise ValueError("查询区间须大于零且不超过十年")
        return sorted((item for event in self.series() for item in self.expand(event, low, high)), key=lambda e: (e["start_at"], e["id"]))
