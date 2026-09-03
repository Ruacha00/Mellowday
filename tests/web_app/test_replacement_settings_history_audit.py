import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
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


def test_replacement_history_reset_and_operation_records_are_route_owned(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url:
        with Client(base_url=base_url) as client:
            response = client.post(
                "/api/chat",
                json={"conversation_id": "review-me", "content": "A stored transcript"},
            )
            assert response.status_code == 200

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 520, "height": 640})
            audit_requests = 0

            def supply_audit(route, request) -> None:
                nonlocal audit_requests
                audit_requests += 1
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "events": [
                                {
                                    "sequence": 8,
                                    "type": "tool_failed",
                                    "occurred_at": 42,
                                    "conversation_id": "review-me",
                                    "details": {
                                        "tool": "save_note",
                                        "reason": "backend unavailable",
                                        "payload": "x" * 320,
                                        "undo": {
                                            "tool": "delete_note",
                                            "arguments": {"note_id": "note-1"},
                                        },
                                    },
                                }
                            ]
                        }
                    ),
                )

            page.route("**/api/settings/audit", supply_audit)
            page.goto(f"{base_url}/#/settings")
            expect(page.get_by_role("heading", name="外观", exact=True)).to_be_visible()
            assert audit_requests == 0

            navigation = page.get_by_role("navigation", name="设置二级导航")
            assert navigation.evaluate("element => element.scrollWidth > element.clientWidth")
            delayed_history = []

            def delay_history(route, request) -> None:
                delayed_history.append(route)

            page.route("**/api/conversations", delay_history)
            page.get_by_role("link", name="对话历史", exact=True).click()
            expect(page).to_have_url(f"{base_url}/#/settings/history")
            expect(
                page.get_by_role("heading", name="对话历史", exact=True, level=1)
            ).to_be_visible()
            expect(page.get_by_text("正在加载对话历史…", exact=True)).to_be_visible()
            assert delayed_history
            with page.expect_response(
                lambda response: response.url
                == f"{base_url}/api/conversations"
            ):
                delayed_history[0].continue_()
            history_item = page.locator(".history-list-item").filter(
                has_text="A stored transcript"
            )
            expect(history_item).to_be_visible()
            page.unroute("**/api/conversations", delay_history)

            def fail_history(route, request) -> None:
                route.fulfill(status=503, body="Unavailable")

            page.route("**/api/conversations", fail_history)
            page.locator(".history-list-section").get_by_role(
                "button", name="刷新", exact=True
            ).click()
            expect(page.get_by_role("alert")).to_contain_text("对话历史加载失败")
            page.unroute("**/api/conversations", fail_history)
            page.get_by_role("alert").get_by_role("button", name="重试").click()
            expect(history_item).to_be_visible()
            history_item.click()
            transcript = page.get_by_role("list", name="已存储的对话转录")
            expect(transcript.get_by_text("A stored transcript", exact=True)).to_be_visible()
            expect(
                transcript.get_by_text("I heard: A stored transcript", exact=True)
            ).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            reset = page.get_by_role("button", name="重置此对话", exact=True)
            reset.click()
            dialog = page.get_by_role("dialog", name="重置这个对话？")
            expect(dialog.get_by_text("不会删除记忆或生活记录", exact=False)).to_be_visible()
            expect(dialog.get_by_role("button", name="取消", exact=True)).to_be_focused()
            dialog.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(reset).to_be_focused()

            reset.click()
            page.get_by_role("dialog", name="重置这个对话？").get_by_role(
                "button", name="确认重置", exact=True
            ).click()
            expect(page.locator(".history-page .settings-notice")).to_contain_text(
                "共移除 2 条消息"
            )
            expect(page.get_by_text("还没有已存储的对话。", exact=True)).to_be_visible()

            page.get_by_role("link", name="操作记录", exact=True).click()
            expect(page).to_have_url(f"{base_url}/#/settings/audit")
            expect(page.get_by_text("tool_failed", exact=True)).to_be_visible()
            expect(page.get_by_text("save_note", exact=True)).to_be_visible()
            page.get_by_text("查看记录详情", exact=True).click()
            expect(page.get_by_text("backend unavailable", exact=False)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert audit_requests == 1

            page.go_back()
            expect(page).to_have_url(f"{base_url}/#/settings/history")
            page.go_forward()
            expect(page).to_have_url(f"{base_url}/#/settings/audit")
            assert audit_requests == 2
            browser.close()


def test_replacement_history_and_operation_records_ignore_obsolete_loads(
    tmp_path: Path,
) -> None:
    app = create_app(
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            response = client.post(
                "/api/chat",
                json={"conversation_id": "late-history", "content": "late transcript"},
            )
            assert response.status_code == 200
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 881, "height": 780})
        delayed_audit = []

        def delay_audit(route, request) -> None:
            delayed_audit.append(route)

        page.route("**/api/settings/audit", delay_audit)
        page.goto(f"{base_url}/#/settings/audit")
        expect(page.get_by_text("正在加载操作记录…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_audit
        delayed_audit[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "events": [
                        {
                            "sequence": 99,
                            "type": "late_failure",
                            "occurred_at": 42,
                            "conversation_id": None,
                            "details": {"reason": "late payload"},
                        }
                    ]
                }
            ),
        )
        expect(page.get_by_text("late_failure", exact=True)).not_to_be_visible()
        page.unroute("**/api/settings/audit", delay_audit)

        def fail_audit(route, request) -> None:
            route.fulfill(status=503, body="Unavailable")

        page.route("**/api/settings/audit", fail_audit)
        page.get_by_role("link", name="设置", exact=True).click()
        page.get_by_role("link", name="操作记录", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("操作记录加载失败")
        page.unroute("**/api/settings/audit", fail_audit)
        page.get_by_role("alert").get_by_role("button", name="重试").click()
        expect(page.get_by_role("alert")).not_to_be_visible()
        expect(
            page.locator(".operation-list-section").get_by_role(
                "button", name="刷新", exact=True
            )
        ).to_be_visible()

        delayed_detail = []

        def delay_history_detail(route, request) -> None:
            delayed_detail.append(route)

        page.route("**/api/conversations/late-history", delay_history_detail)
        page.get_by_role("link", name="对话历史", exact=True).click()
        history_item = page.locator(".history-list-item").filter(
            has_text="late transcript"
        )
        expect(history_item).to_be_visible()
        history_item.click()
        expect(page.get_by_text("正在加载会话内容…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        assert delayed_detail
        delayed_detail[0].continue_()
        expect(page.locator(".history-transcript")).to_have_count(0)
        browser.close()
