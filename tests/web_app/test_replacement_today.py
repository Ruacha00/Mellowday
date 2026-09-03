import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from httpx import Client
from playwright.sync_api import expect, sync_playwright

from mellowday.agent_core import FakeProvider
from mellowday.web_app import create_app


@contextmanager
def running_server(app: FastAPI) -> Iterator[str]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("test server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("test server did not stop")


def test_replacement_today_derives_records_and_uses_bounded_source_actions(
    tmp_path: Path,
) -> None:
    generated_at = datetime(2026, 9, 1, 1, tzinfo=timezone.utc).timestamp()
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        installation_timezone="Asia/Shanghai",
        daily_review_clock=lambda: generated_at,
        note_clock=lambda: generated_at,
        audit_path=None,
    )

    with running_server(app) as base_url:
        with Client(base_url=base_url) as client:
            client.post(
                "/api/settings/tasks",
                json={"title": "补交报告", "deadline": "2026-08-31"},
            ).raise_for_status()
            due_task = client.post(
                "/api/settings/tasks",
                json={"title": "今日任务", "deadline": "2026-09-01"},
            )
            due_task.raise_for_status()
            client.post(
                "/api/settings/tasks",
                json={"title": "周末计划", "deadline": "2026-09-05"},
            ).raise_for_status()
            client.post(
                "/api/settings/reminders",
                json={
                    "message": "参加例会",
                    "due_at": "2030-09-01T10:00:00+08:00",
                },
            ).raise_for_status()
            client.post(
                "/api/settings/calendar-events",
                json={
                    "title": "午餐",
                    "start_at": "2026-09-01T12:00:00+08:00",
                    "details": "楼下见",
                },
            ).raise_for_status()
            client.post(
                "/api/settings/notes",
                json={"title": "会议准备", "content": "带上数据"},
            ).raise_for_status()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 520, "height": 640})
            page.goto(f"{base_url}/#/today")
            page.wait_for_load_state("domcontentloaded")

            expect(page.get_by_role("heading", name="今日概览", exact=True)).to_be_visible()
            expect(page.get_by_text("补交报告", exact=True)).to_be_visible()
            expect(page.get_by_text("今日任务", exact=True)).to_be_visible()
            expect(page.get_by_text("周末计划", exact=True)).not_to_be_visible()
            expect(page.get_by_text("参加例会", exact=True)).to_be_visible()
            expect(page.get_by_text("午餐", exact=True)).to_be_visible()
            expect(page.get_by_text("带上数据", exact=True)).to_be_visible()

            expect(page.get_by_role("link", name="在任务中编辑").first).to_have_attribute(
                "href", "#/life/tasks"
            )
            expect(page.get_by_role("link", name="在提醒中编辑")).to_have_attribute(
                "href", "#/life/reminders"
            )
            expect(page.get_by_role("link", name="在日历中编辑")).to_have_attribute(
                "href", "#/life/calendar"
            )
            expect(page.get_by_role("link", name="在笔记中查看")).to_have_attribute(
                "href", "#/life/notes"
            )

            page.get_by_role("button", name="完成任务：今日任务").click()
            expect(page.get_by_role("status").filter(has_text="已完成“今日任务”。")).to_be_visible()
            expect(page.get_by_text("今日任务", exact=True)).not_to_be_visible()
            with Client(base_url=base_url) as client:
                stored_task = client.get(
                    f"/api/settings/tasks/{due_task.json()['task']['id']}"
                )
            stored_task.raise_for_status()
            assert stored_task.json()["task"]["completed"] is True

            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth"
            )
            page.get_by_role("link", name="在日历中编辑").click()
            expect(page).to_have_url(f"{base_url}/#/life/calendar")
            page.go_back()
            expect(page).to_have_url(f"{base_url}/#/today")
            expect(page.get_by_role("heading", name="今日概览", exact=True)).to_be_visible()
            browser.close()


def test_replacement_today_ignores_late_results_and_keeps_stale_data(
    tmp_path: Path,
) -> None:
    generated_at = datetime(2026, 9, 1, 1, tzinfo=timezone.utc).timestamp()
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        installation_timezone="Asia/Shanghai",
        daily_review_clock=lambda: generated_at,
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 520, "height": 640})
        page.goto(f"{base_url}/#/today")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_role("heading", name="今日概览", exact=True)).to_be_visible()

        delayed_routes = []

        def delay_review(route, _request) -> None:
            delayed_routes.append(route)

        page.route("**/api/settings/daily-review", delay_review)
        page.get_by_role("button", name="刷新概览", exact=True).click()
        expect(page.get_by_role("button", name="正在刷新", exact=True)).to_be_disabled()
        page.get_by_role("link", name="查看全部任务", exact=True).click()
        expect(page).to_have_url(f"{base_url}/#/life/tasks")
        assert delayed_routes
        delayed_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "daily_review": {
                        "date": "2026-09-01",
                        "timezone": "Asia/Shanghai",
                        "generated_at": generated_at + 1,
                        "tasks": [
                            {
                                "id": "late",
                                "title": "迟到的今日结果",
                                "details": None,
                                "deadline": "2026-09-01",
                                "timing": "due_today",
                            }
                        ],
                        "reminders": [],
                        "calendar_events": [],
                        "notes": [],
                    }
                }
            ),
        )
        expect(page.get_by_text("迟到的今日结果", exact=True)).not_to_be_visible()

        page.unroute("**/api/settings/daily-review", delay_review)
        page.goto(f"{base_url}/#/today")
        expect(page.get_by_role("heading", name="今日概览", exact=True)).to_be_visible()
        page.route(
            "**/api/settings/daily-review",
            lambda route: route.fulfill(status=503, body="Unavailable"),
        )
        page.get_by_role("button", name="刷新概览", exact=True).click()
        expect(page.locator(".today-page")).to_have_attribute("data-state", "stale")
        expect(page.get_by_text("上次成功加载的概览", exact=False)).to_be_visible()
        expect(page.get_by_text("今天没有日历事件。", exact=True)).to_be_visible()
        browser.close()
