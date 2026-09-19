"""Durable single-user scheduling and notification delivery.

The scheduler never grants tool permissions or starts an autonomous agent. Reports
are grounded in the current calendar; optional formatting receives read-only data.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from mellowday.personal_assistant.calendar_store import CalendarStore, UTC, iso, moment, RECURRENCES
from mellowday.storage.store import Store

log = logging.getLogger(__name__)
REPORT_SKILL = "查询订阅时区的当天日程；按时间排序；逐条呈现时间、标题；没有日程时明确说明；不推测、不创建或修改任何记录。"
SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule_subscriptions (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_notifications (id TEXT PRIMARY KEY, payload TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, published INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS schedule_instances (instance_key TEXT PRIMARY KEY, notification_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class ScheduleService:
    def __init__(self, store: Store, *, session_exists: Callable[[str], bool] | None = None, publish_report: Callable | None = None, report_formatter: Callable | None = None, clock: Callable | None = None):
        self.store = store
        self.calendar = CalendarStore(store)
        self.session_exists = session_exists or (lambda _: False)
        self.publish_report = publish_report
        self.report_formatter = report_formatter
        self.clock = clock or (lambda: datetime.now(UTC))
        self._task = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None
        with self.store._connect() as db:
            db.executescript(SCHEMA)

    def subscriptions(self) -> list[dict]:
        with self.store._connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM schedule_subscriptions ORDER BY id")]

    def save_subscription(self, payload: dict, subscription_id: str | None = None) -> dict:
        allowed = {"title", "time", "timezone", "recurrence", "weekday", "session_id", "enabled"}
        if set(payload) - allowed:
            raise ValueError("包含未知订阅字段")
        old = next((s for s in self.subscriptions() if s["id"] == subscription_id), None)
        if subscription_id and old is None:
            raise KeyError(subscription_id)
        data = {"id": subscription_id or uuid.uuid4().hex, "timezone": "Asia/Shanghai", "recurrence": "daily", "enabled": True, "created_at": iso(self.clock()), **(old or {}), **payload}
        if not isinstance(data.get("title"), str) or not data["title"].strip() or len(data["title"]) > 500:
            raise ValueError("订阅标题不能为空或过长")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(data.get("time", ""))):
            raise ValueError("订阅时间应为 HH:MM")
        try:
            ZoneInfo(data["timezone"])
        except (KeyError, TypeError) as exc:
            raise ValueError("时区无效") from exc
        if data["recurrence"] not in RECURRENCES - {"none"}:
            raise ValueError("订阅支持 daily/weekly/weekdays")
        data.setdefault("weekday", moment(data["created_at"]).astimezone(ZoneInfo(data["timezone"])).weekday())
        if type(data["weekday"]) is not int or not 0 <= data["weekday"] <= 6:
            raise ValueError("weekday 必须为 0（周一）至 6（周日）")
        if type(data["enabled"]) is not bool:
            raise ValueError("enabled 必须是布尔值")
        if not isinstance(data.get("session_id"), str) or not self.session_exists(data["session_id"]):
            raise ValueError("接收会话不存在，请先创建或选择聊天")
        data.update(updated_at=iso(self.clock()), pause_reason=None)
        with self.store._connect() as db:
            db.execute("INSERT OR REPLACE INTO schedule_subscriptions VALUES (?, ?)", (data["id"], json.dumps(data, ensure_ascii=False)))
        return data

    def delete_subscription(self, subscription_id: str) -> None:
        with self.store._connect() as db:
            if not db.execute("DELETE FROM schedule_subscriptions WHERE id=?", (subscription_id,)).rowcount:
                raise KeyError(subscription_id)

    def pause_session(self, session_id: str) -> None:
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id,payload FROM schedule_subscriptions").fetchall():
                sub = json.loads(row[1])
                if sub["session_id"] == session_id:
                    sub.update(enabled=False, pause_reason="接收会话已删除")
                    db.execute("UPDATE schedule_subscriptions SET payload=? WHERE id=?", (json.dumps(sub, ensure_ascii=False), row[0]))

    def notifications(self, *, unread_only: bool = False) -> list[dict]:
        with self.store._connect() as db:
            rows = db.execute("SELECT payload,read FROM schedule_notifications" + (" WHERE read=0" if unread_only else "") + " ORDER BY rowid DESC LIMIT 500").fetchall()
        return [{**json.loads(row[0]), "read": bool(row[1])} for row in rows]

    def mark_read(self, notification_id: str) -> None:
        with self.store._connect() as db:
            if not db.execute("UPDATE schedule_notifications SET read=1 WHERE id=?", (notification_id,)).rowcount:
                raise KeyError(notification_id)

    def reports_for_session(self, session_id: str) -> list[dict]:
        # Authoritative durable report bodies, useful for history integration.
        with self.store._connect() as db:
            rows = db.execute("SELECT payload,read FROM schedule_notifications WHERE "
                "json_extract(payload, '$.kind')='report' AND "
                "json_extract(payload, '$.session_id')=? ORDER BY rowid", (session_id,)).fetchall()
        return [{**json.loads(row[0]), "read": bool(row[1])} for row in rows]

    def _latest(self, sub: dict, now: datetime) -> datetime | None:
        zone = ZoneInfo(sub["timezone"])
        local = now.astimezone(zone)
        hour, minute = map(int, sub["time"].split(":"))
        anchor = moment(sub["created_at"]).astimezone(zone)
        for offset in range(8):
            day = local.date() - timedelta(days=offset)
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            utc = at.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) != at.replace(tzinfo=None):
                continue
            if utc > now or utc < moment(sub["created_at"]):
                continue
            if sub["recurrence"] == "weekdays" and day.weekday() >= 5:
                continue
            if sub["recurrence"] == "weekly" and day.weekday() != sub.get("weekday", anchor.weekday()):
                continue
            return utc
        return None

    def _notification(self, *, kind: str, title: str, body: str, scheduled: datetime, event_id=None, session_id=None, **extra) -> dict:
        return {"id": uuid.uuid4().hex, "kind": kind, "title": title, "body": body, "event_id": event_id, "session_id": session_id, "scheduled_at": iso(scheduled), "created_at": iso(self.clock()), "read": False, **extra}

    def _save(self, notification: dict, instances: list[tuple[str, dict]], *, subscription: dict | None = None) -> bool:
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            accepted = []
            for key, event in instances:
                if db.execute("SELECT 1 FROM schedule_instances WHERE instance_key=?", (key,)).fetchone():
                    continue
                if event:
                    row = db.execute("SELECT updated_at,status,due_at FROM records WHERE id=?", (event["id"],)).fetchone()
                    if not row or row[0] != event["updated_at"] or row[1] != event["status"]:
                        continue
                    # Exceptions can change without touching the series record.
                    patch = db.execute("SELECT payload FROM calendar_exceptions WHERE event_id=? AND occurrence_start=?", (event["id"], event["occurrence_start"])).fetchone()
                    if patch:
                        current = json.loads(patch[0])
                        if any(current.get(k) != event.get(k) for k in ("status", "start_at", "reminder_minutes")):
                            continue
                if subscription:
                    row = db.execute("SELECT payload FROM schedule_subscriptions WHERE id=?", (subscription["id"],)).fetchone()
                    if not row or json.loads(row[0]) != subscription or not self.session_exists(subscription["session_id"]):
                        continue
                accepted.append(key)
            if not accepted:
                return False
            # All grouped data must remain valid, otherwise rebuild next tick.
            if len(accepted) != len(instances):
                return False
            db.execute("INSERT INTO schedule_notifications(id,payload) VALUES (?,?)", (notification["id"], json.dumps(notification, ensure_ascii=False)))
            db.executemany("INSERT INTO schedule_instances VALUES (?,?)", [(key, notification["id"]) for key in accepted])
            return True

    @staticmethod
    def report_body(events: list[dict], zone: str) -> str:
        if not events:
            return "今天没有已安排的日程。"
        lines = ["今天的安排："]
        for event in events:
            at = moment(event["start_at"]).astimezone(ZoneInfo(zone))
            end = moment(event["end_at"]).astimezone(ZoneInfo(zone))
            when = "全天" if event["all_day"] else f"{at:%H:%M}–{end:%H:%M}"
            lines.append(f"• {when} {event['title']}")
        return "\n".join(lines)

    async def tick(self, now: datetime | None = None) -> None:
        async with self._lock:
            await self._tick(now or self.clock())

    async def _tick(self, now: datetime) -> None:
        now = now.astimezone(UTC)
        with self.store._connect() as db:
            done = {r[0] for r in db.execute("SELECT instance_key FROM schedule_instances")}
        missed = []
        for series in self.calendar.series():
            # Exceptions can use a different lead than their series. Include
            # their maximum lead and earliest moved start when expanding.
            with self.store._connect() as db:
                patches = [json.loads(r[0]) for r in db.execute("SELECT payload FROM calendar_exceptions WHERE event_id=?", (series["id"],))]
            leads = [value for value in [series["reminder_minutes"], *(p["reminder_minutes"] for p in patches)] if value is not None]
            if not leads:
                continue
            lead = max(leads)
            low = moment(series["start_at"]) - timedelta(minutes=lead)
            if patches:
                low = min(low, *(moment(p["start_at"]) for p in patches))
            for event in self.calendar.expand(series, low, now + timedelta(minutes=lead, microseconds=1)):
                if event["reminder_minutes"] is None:
                    continue
                due = moment(event["start_at"]) - timedelta(minutes=event["reminder_minutes"])
                key = f"event:{event['id']}:{event['occurrence_start']}"
                if due > now or key in done:
                    continue
                local_time = moment(event["start_at"]).astimezone(ZoneInfo(event["timezone"]))
                body = f"{event['title']} · {local_time:%Y-%m-%d %H:%M}"
                if now - due > timedelta(minutes=2):
                    missed.append((key, event, due, body))
                else:
                    self._save(self._notification(kind="reminder", title=event["title"], body=body, scheduled=due, event_id=event["id"], occurrence_start=event["occurrence_start"]), [(key, event)])
        if missed:
            body = "错过的提醒：\n" + "\n".join(f"• {m[3]}" for m in missed)
            notification = self._notification(kind="reminder", title=f"有 {len(missed)} 条过期提醒", body=body, scheduled=max(m[2] for m in missed), event_id=missed[0][1]["id"], occurrence_start=missed[0][1]["occurrence_start"], missed=True, events=[{"event_id": m[1]["id"], "occurrence_start": m[1]["occurrence_start"]} for m in missed])
            self._save(notification, [(m[0], m[1]) for m in missed])
        for sub in self.subscriptions():
            if not sub["enabled"]:
                continue
            if not self.session_exists(sub["session_id"]):
                self.pause_session(sub["session_id"])
                continue
            due = self._latest(sub, now)
            if due is None:
                continue
            key = f"subscription:{sub['id']}:{iso(due)}"
            if key in done:
                continue
            local = now.astimezone(ZoneInfo(sub["timezone"]))
            day = local.replace(hour=0, minute=0, second=0, microsecond=0)
            events = self.calendar.events(day, day + timedelta(days=1))
            body = self.report_body(events, sub["timezone"])
            format_error = None
            if self.report_formatter:
                try:
                    formatted = self.report_formatter(REPORT_SKILL, events, sub)
                    if inspect.isawaitable(formatted):
                        formatted = await asyncio.wait_for(formatted, timeout=30)
                    if not isinstance(formatted, str) or not formatted.strip():
                        raise ValueError("empty report")
                    body = formatted
                except Exception as exc:
                    format_error = type(exc).__name__
                    # Grounded deterministic report remains available.
            if now - due > timedelta(minutes=2):
                body = "恢复后补发最近一期汇报，较早期次不再逐条补发。\n\n" + body
            notification = self._notification(kind="report", title=sub["title"], body=body, scheduled=due, session_id=sub["session_id"], subscription_id=sub["id"], format_error=format_error)
            self._save(notification, [(key, {})], subscription=sub)
        await self._publish()
        with self.store._connect() as db:
            db.execute("INSERT OR REPLACE INTO schedule_state VALUES ('last_tick', ?)", (iso(now),))
        self.last_error = None

    async def _publish(self) -> None:
        if not self.publish_report:
            return
        with self.store._connect() as db:
            pending = [json.loads(row[0]) for row in db.execute("SELECT payload FROM schedule_notifications WHERE published=0")]
        for notification in pending:
            if notification["kind"] != "report":
                continue
            if not self.session_exists(notification["session_id"]):
                self.pause_session(notification["session_id"])
                continue
            try:
                result = self.publish_report(notification)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=30)
                if result is False:
                    continue
                with self.store._connect() as db:
                    db.execute("UPDATE schedule_notifications SET published=1 WHERE id=?", (notification["id"],))
            except Exception:
                log.exception("Unable to append scheduled report; durable outbox retained")

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="mellowday-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self.last_error = type(exc).__name__
                log.exception("Scheduler tick failed; retrying on next interval")
            await asyncio.sleep(15)
