from datetime import datetime, timedelta
import asyncio
import json
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from mellowday.storage.store import Store
from mellowday.personal_assistant.calendar_store import CalendarStore, moment, iso
from mellowday.personal_assistant.schedule import ScheduleService
from mellowday.personal_assistant import schedule_tools
from mellowday.web_app.calendar_routes import create_router


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def event(**kwargs):
    return {"title": "会议", "start_at": "2026-09-21T09:00:00+08:00", "end_at": "2026-09-21T10:00:00+08:00", "timezone": "Asia/Shanghai", **kwargs}


def run(awaitable):
    return asyncio.run(awaitable)


def test_interval_overlap_legacy_edits_share_records(store):
    old = store.create_record("calendar", {"title": "旧安排", "due_at": "2026-09-21T08:00:00+08:00"})
    calendar = CalendarStore(store)
    new = calendar.create(event())
    found = calendar.events("2026-09-21T08:30:00+08:00", "2026-09-21T09:30:00+08:00")
    assert {r["id"] for r in found} == {old["id"], new["id"]}
    updated = calendar.update(old["id"], {"title": "已修改", "end_at": "2026-09-21T09:30:00+08:00"})
    assert store.get_record("calendar", old["id"])["title"] == "已修改"
    assert len(store.list_records("calendar")) == 2
    store.update_record("calendar", old["id"], {"due_at": "2026-09-22T08:00:00+08:00"})
    assert calendar.get(old["id"])["end_at"] == "2026-09-22T01:30:00+00:00"
    assert updated["operation_id"]


def test_weekdays_single_cancel_and_move(store):
    calendar = CalendarStore(store)
    created = calendar.create(event(recurrence="weekdays"))
    rows = calendar.events("2026-09-21", "2026-09-28")
    assert len(rows) == 5
    original = rows[0]["occurrence_start"]
    calendar.update(created["id"], {"start_at": "2026-10-01T12:00:00+08:00", "end_at": "2026-10-01T13:00:00+08:00"}, scope="single", occurrence_start=original)
    moved = calendar.events("2026-10-01", "2026-10-02")
    assert len(moved) == 2
    assert any(r["occurrence_start"] == original for r in moved)
    calendar.delete(created["id"], scope="single", occurrence_start=rows[1]["occurrence_start"])
    assert len(calendar.events("2026-09-21", "2026-09-28")) == 3
    calendar.delete(created["id"])
    assert calendar.events("2026-10-01", "2026-10-02") == []


def test_timezone_recurrence_keeps_wall_clock(store):
    calendar = CalendarStore(store)
    calendar.create(event(start_at="2026-10-31T09:00:00-04:00", end_at="2026-10-31T10:00:00-04:00", timezone="America/New_York", recurrence="daily"))
    rows = calendar.events("2026-10-31T00:00:00Z", "2026-11-03T00:00:00Z")
    assert rows[0]["start_at"] == "2026-10-31T13:00:00+00:00"
    assert rows[1]["start_at"] == "2026-11-01T14:00:00+00:00"
    with pytest.raises(ValueError):
        calendar.create(event(start_at="2026-03-08T02:30:00", end_at="2026-03-08T04:00:00", timezone="America/New_York"))


def test_restart_catchup_is_one_summary_no_duplicates(store):
    now = moment("2026-09-24T10:00:00+08:00")
    service = ScheduleService(store, clock=lambda: now)
    service.calendar.create(event(recurrence="daily", reminder_minutes=0))
    run(service.tick())
    notifications = service.notifications()
    assert len(notifications) == 1
    assert len(notifications[0]["events"]) == 4
    assert notifications[0]["missed"]
    restarted = ScheduleService(Store(store.data_dir), clock=lambda: now)
    run(restarted.tick())
    assert len(restarted.notifications()) == 1
    restarted.mark_read(notifications[0]["id"])
    assert restarted.notifications(unread_only=True) == []
    now += timedelta(days=1)
    run(restarted.tick())
    assert len(restarted.notifications()) == 2


def test_exact_due_cancel_and_legacy_reminder(store):
    now = moment("2026-09-21T08:50:00+08:00")
    service = ScheduleService(store, clock=lambda: now)
    cancelled = service.calendar.create(event(reminder_minutes=10))
    service.calendar.delete(cancelled["id"])
    legacy = store.create_record("reminders", {"title": "喝水", "due_at": iso(now)})
    run(service.tick())
    assert len(service.notifications()) == 1
    assert service.notifications()[0]["event_id"] == legacy["id"]
    assert not service.notifications()[0].get("missed")


def test_subscription_latest_only_durable_publish_and_deleted_session(store):
    now = moment("2026-09-21T07:00:00+08:00")
    exists = {"chat"}
    published = []
    service = ScheduleService(store, clock=lambda: now, session_exists=lambda sid: sid in exists, publish_report=lambda n: published.append(n))
    sub = service.save_subscription({"title": "早间安排", "time": "08:00", "session_id": "chat"})
    now += timedelta(days=3, hours=2)
    service.calendar.create(event(start_at="2026-09-24T10:00:00+08:00", end_at="2026-09-24T11:00:00+08:00"))
    run(service.tick())
    assert len(published) == 1
    assert "会议" in published[0]["body"]
    assert "补发最近一期" in published[0]["body"]
    assert service.reports_for_session("chat")[0]["id"] == published[0]["id"]
    run(service.tick())
    assert len(published) == 1
    exists.clear()
    now += timedelta(days=1)
    run(service.tick())
    assert service.subscriptions()[0]["enabled"] is False
    assert service.subscriptions()[0]["pause_reason"]
    assert len(published) == 1
    exists.add("new")
    service.save_subscription({"session_id": "new", "enabled": True}, sub["id"])
    run(service.tick())
    assert published[-1]["session_id"] == "new"


def test_formatter_failure_preserves_grounded_fallback(store):
    now = moment("2026-09-21T07:00:00+08:00")
    async def broken(*args):
        raise RuntimeError("provider unavailable")
    service = ScheduleService(store, clock=lambda: now, session_exists=lambda _: True, report_formatter=broken)
    service.save_subscription({"title": "安排", "time": "08:00", "session_id": "chat"})
    now += timedelta(hours=1)
    run(service.tick())
    report = service.notifications()[0]
    assert report["format_error"] == "RuntimeError"
    assert report["body"] == "今天没有已安排的日程。"


def test_api_and_tools_validate_and_target_single(store):
    service = ScheduleService(store, session_exists=lambda _: True)
    app = FastAPI()
    app.include_router(create_router(service))
    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/calendar/events", json=event(end_at="2026-09-20T09:00:00Z"))).status_code == 422
            response = await client.post("/api/calendar/events", json=event(recurrence="daily"))
            assert response.status_code == 200
            ident = response.json()["event"]["id"]
            assert (await client.put(f"/api/calendar/events/{ident}?scope=single", json={"title": "a"})).status_code == 422
            assert (await client.get("/api/calendar/events/missing")).status_code == 404
            return ident
    ident = run(requests())
    result = json.loads(run(schedule_tools.execute_tool(service, "calendar_subscription_create", {"title": "日报", "time": "09:00"}, session_id="chat")))
    assert result["subscription"]["session_id"] == "chat"
    emitted = []
    run(schedule_tools.execute_tool(service, "calendar_open", {"event_id": ident}, emit=emitted.append))
    assert emitted[0]["type"] == "calendar_open"


def test_publication_retry_uses_stable_notification_id(store):
    now = moment("2026-09-21T07:00:00+08:00")
    attempts = []
    def fail_once(notification):
        attempts.append(notification["id"])
        if len(attempts) == 1:
            raise RuntimeError("offline")
    service = ScheduleService(store, clock=lambda: now, session_exists=lambda _: True, publish_report=fail_once)
    service.save_subscription({"title": "日报", "time": "08:00", "session_id": "chat"})
    now += timedelta(hours=1)
    run(service.tick())
    run(service.tick())
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert len(service.notifications()) == 1


def test_exception_edit_preserves_moved_time_and_own_reminder(store):
    now = moment("2026-09-21T11:30:00+08:00")
    service = ScheduleService(store, clock=lambda: now)
    created = service.calendar.create(event(recurrence="daily"))
    original = created["start_at"]
    service.calendar.update(created["id"], {"start_at": "2026-09-21T12:00:00+08:00", "end_at": "2026-09-21T13:00:00+08:00", "reminder_minutes": 30}, scope="single", occurrence_start=original)
    updated = service.calendar.update(created["id"], {"title": "改名"}, scope="single", occurrence_start=original)
    assert updated["start_at"] == "2026-09-21T04:00:00+00:00"
    run(service.tick())
    assert service.notifications()[0]["title"] == "改名"
    assert service.notifications()[0]["scheduled_at"] == iso(now)


def test_all_day_dst_has_local_midnight_boundaries(store):
    calendar = CalendarStore(store)
    calendar.create(event(start_at="2026-10-31T00:00:00-04:00", end_at="2026-11-01T00:00:00-04:00", timezone="America/New_York", recurrence="daily", all_day=True))
    events = calendar.events("2026-11-01T04:00:00Z", "2026-11-02T05:00:00Z")
    assert len(events) == 1
    assert moment(events[0]["end_at"]) - moment(events[0]["start_at"]) == timedelta(hours=25)


def test_weekly_and_weekday_subscription_dates(store):
    now = moment("2026-09-21T07:00:00+08:00")  # Monday
    service = ScheduleService(store, clock=lambda: now, session_exists=lambda _: True)
    weekly = service.save_subscription({"title": "每周", "time": "08:00", "session_id": "chat", "recurrence": "weekly"})
    weekday = service.save_subscription({"title": "工作日", "time": "08:00", "session_id": "chat", "recurrence": "weekdays"})
    sunday = moment("2026-09-27T12:00:00+08:00")
    assert service._latest(weekly, sunday) == moment("2026-09-21T08:00:00+08:00")
    assert service._latest(weekday, sunday) == moment("2026-09-25T08:00:00+08:00")


def test_scheduler_cancel_and_changed_reminder_race_revalidated(store):
    now = moment("2026-09-21T09:00:00+08:00")
    service = ScheduleService(store, clock=lambda: now)
    created = service.calendar.create(event(reminder_minutes=0))
    stale = service.calendar.events(now, now + timedelta(hours=1))[0]
    service.calendar.delete(created["id"], scope="single", occurrence_start=stale["occurrence_start"])
    notification = service._notification(kind="reminder", title="旧", body="旧", scheduled=now)
    assert not service._save(notification, [("stale", stale)])
    assert service.notifications() == []


def test_lifecycle_starts_and_stops_without_orphan_task(store):
    async def exercise():
        service = ScheduleService(store)
        await service.start()
        first = service._task
        await service.start()
        assert service._task is first
        await asyncio.sleep(0)
        await service.stop()
        assert first.done()
        assert service._task is None
    run(exercise())


def test_weekly_subscription_uses_selected_weekday(store):
    now = moment("2026-09-21T07:00:00+08:00")
    service = ScheduleService(store, session_exists=lambda _: True, clock=lambda: now)
    sub = service.save_subscription(dict(title="日程", time="08:00", timezone="Asia/Shanghai",
        recurrence="weekly", weekday=2, session_id="chat"))
    assert service._latest(sub, moment("2026-09-22T09:00:00+08:00")) is None
    assert service._latest(sub, moment("2026-09-23T09:00:00+08:00")) == moment("2026-09-23T08:00:00+08:00")
    for invalid in (-1, 7, True, "2"):
        with pytest.raises(ValueError):
            service.save_subscription({**{k: sub[k] for k in ('title','time','timezone','recurrence','session_id')}, 'weekday': invalid})
