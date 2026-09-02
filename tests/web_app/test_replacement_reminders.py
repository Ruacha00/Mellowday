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


def test_replacement_life_reminders_supports_the_complete_lifecycle(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 520, "height": 640})
        page.goto(f"{base_url}/replacement#/life/reminders")

        expect(page.get_by_role("navigation", name="生活二级导航")).to_be_visible()
        expect(page.get_by_text("还没有提醒。", exact=True)).to_be_visible()
        message = page.get_by_label("提醒内容", exact=True)
        message.fill("Read reminder spec")
        page.get_by_label("提醒时间", exact=True).fill("2030-09-04T09:00")
        page.get_by_role("button", name="添加提醒", exact=True).click()
        expect(page.get_by_role("status", name="提醒状态")).to_contain_text(
            "提醒已添加"
        )
        with Client(base_url=base_url) as client:
            reminder = client.get("/api/settings/reminders").json()["reminders"][0]
            changed = client.patch(
                f"/api/settings/reminders/{reminder['id']}",
                json={"conversation_id": "planning"},
            )
        assert changed.status_code == 200
        page.reload()
        expect(page.get_by_text("Read reminder spec", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        inspect = page.get_by_role("button", name="查看 Read reminder spec")
        inspect.click()
        expect(page.get_by_text("投递会话", exact=True)).to_be_visible()
        expect(page.get_by_text("planning", exact=True)).to_be_visible()

        page.get_by_role("button", name="编辑 Read reminder spec").click()
        expect(message).to_be_focused()
        message.fill("Review reminder spec")
        page.get_by_label("提醒时间", exact=True).fill("2030-09-05T10:30")
        page.get_by_role("button", name="保存提醒", exact=True).click()
        expect(page.get_by_role("status", name="提醒状态")).to_contain_text(
            "提醒已保存并重新安排"
        )
        expect(page.get_by_text("Review reminder spec", exact=True)).to_be_visible()
        details = page.locator(".reminder-details")
        expect(details).to_contain_text("planning")
        expect(details).to_contain_text("10:30")
        with Client(base_url=base_url) as client:
            persisted = client.get(f"/api/settings/reminders/{reminder['id']}").json()[
                "reminder"
            ]
        assert persisted["conversation_id"] == "planning"

        delete_button = page.get_by_role("button", name="删除 Review reminder spec")
        delete_button.click()
        confirmation = page.get_by_role("dialog", name="删除提醒")
        cancel_delete = confirmation.get_by_role("button", name="取消", exact=True)
        confirm_delete = confirmation.get_by_role("button", name="确认删除", exact=True)
        expect(cancel_delete).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(confirm_delete).to_be_focused()
        page.keyboard.press("Tab")
        expect(cancel_delete).to_be_focused()
        page.keyboard.press("Escape")
        expect(confirmation).not_to_be_visible()
        expect(delete_button).to_be_focused()
        expect(page.get_by_role("status", name="提醒状态")).to_contain_text(
            "已取消删除提醒"
        )

        delete_button.click()

        def fail_delete(route, request) -> None:
            if request.method == "DELETE":
                route.fulfill(status=503, body="Unavailable")
            else:
                route.continue_()

        page.route("**/api/settings/reminders/**", fail_delete)
        confirm_delete.click()
        expect(confirmation.get_by_role("status", name="删除状态")).to_contain_text(
            "提醒删除失败"
        )
        page.unroute("**/api/settings/reminders/**", fail_delete)
        confirm_delete.click()
        expect(page.get_by_role("status", name="提醒状态")).to_contain_text(
            "提醒已删除"
        )
        expect(page.get_by_text("还没有提醒。", exact=True)).to_be_visible()
        browser.close()


def test_replacement_life_reminder_loads_stop_while_live_delivery_continues(
    tmp_path: Path,
) -> None:
    now = 1_788_200_100.0
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
        reminder_clock=lambda: now,
        reminder_poll_interval=0.05,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 520, "height": 640})
        delayed_routes = []
        live_requests: list[str] = []
        page.on(
            "request",
            lambda request: live_requests.append(request.url)
            if "/api/conversations/main/live" in request.url
            else None,
        )

        def delay_reminder_list(route, request) -> None:
            if request.method == "GET":
                delayed_routes.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/reminders", delay_reminder_list)
        page.goto(f"{base_url}/replacement#/life/reminders")
        expect(page.get_by_text("正在加载提醒…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_routes
        delayed_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"reminders":[{"id":"late","message":"Late reminder",'
                '"due_at":"2030-01-01T00:00:00+00:00",'
                '"delivery_state":"scheduled","task_id":null,'
                '"conversation_id":"main","created_at":1,"updated_at":1,'
                '"delivery_attempted_at":null,"delivered_at":null,'
                '"dismissed_at":null,"cancelled_at":null,'
                '"delivery_error":null}]}'
            ),
        )
        expect(page.get_by_text("Late reminder", exact=True)).not_to_be_visible()

        page.unroute("**/api/settings/reminders", delay_reminder_list)
        page.route(
            "**/api/settings/reminders",
            lambda route, request: route.fulfill(status=503, body="Unavailable")
            if request.method == "GET"
            else route.continue_(),
        )
        page.goto(f"{base_url}/replacement#/life/reminders")
        expect(page.get_by_role("alert")).to_contain_text("提醒加载失败")
        page.unroute("**/api/settings/reminders")
        page.get_by_role("button", name="重试", exact=True).click()
        expect(page.get_by_text("还没有提醒。", exact=True)).to_be_visible()

        page.get_by_role("button", name="添加提醒", exact=True).click()
        expect(page.get_by_role("status", name="提醒状态")).to_contain_text(
            "请输入提醒内容"
        )
        expect(page.get_by_label("提醒内容", exact=True)).to_be_focused()
        page.get_by_label("提醒内容", exact=True).fill("No due time")
        page.get_by_role("button", name="添加提醒", exact=True).click()
        expect(page.get_by_role("status", name="提醒状态")).to_contain_text(
            "请选择有效的提醒时间"
        )
        expect(page.get_by_label("提醒时间", exact=True)).to_be_focused()

        due_at = datetime.fromtimestamp(now - 1, timezone.utc).isoformat()
        with Client(base_url=base_url) as client:
            created = client.post(
                "/api/settings/reminders",
                json={"message": "Reminder route delivery", "due_at": due_at},
            )
        assert created.status_code == 201

        page.get_by_role("link", name="对话", exact=True).click()
        transcript = page.get_by_label("会话记录")
        live_message = transcript.get_by_text(
            "Mellowday reminder: Reminder route delivery", exact=True
        )
        expect(live_message).to_be_visible(timeout=5_000)
        expect(live_message).to_have_count(1)
        assert len(live_requests) == 1
        browser.close()
