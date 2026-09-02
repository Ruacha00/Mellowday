import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
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


def test_replacement_diagnostics_polling_is_owned_by_the_active_route(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 881, "height": 780})
        requests = {"status": 0, "events": 0, "logs": 0, "live": 0}

        def record_request(request) -> None:
            if "/api/settings/status" in request.url:
                requests["status"] += 1
            elif "/api/events/recent" in request.url:
                requests["events"] += 1
            elif "/api/logs/recent" in request.url:
                requests["logs"] += 1
            elif "/api/conversations/main/live" in request.url:
                requests["live"] += 1

        page.on("request", record_request)
        page.goto(f"{base_url}/#/today")
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        page.wait_for_timeout(1_700)
        assert {key: requests[key] for key in ("status", "events", "logs")} == {
            "status": 0,
            "events": 0,
            "logs": 0,
        }

        settings_link = page.get_by_role("link", name="设置", exact=True)
        settings_link.focus()
        settings_link.press("Enter")
        expect(page).to_have_url(f"{base_url}/#/settings/appearance")
        diagnostics_link = page.get_by_role("link", name="诊断", exact=True)
        diagnostics_link.focus()
        diagnostics_link.press("Enter")
        expect(page).to_have_url(f"{base_url}/#/settings/diagnostics")
        expect(
            page.get_by_role("heading", name="诊断", exact=True, level=2)
        ).to_be_focused()
        expect(page.get_by_role("heading", name="服务状态", exact=True)).to_be_visible()
        first_cycle = requests.copy()
        assert all(first_cycle[key] == 1 for key in ("status", "events", "logs"))

        page.wait_for_timeout(1_700)
        assert all(
            first_cycle[key] < requests[key] <= first_cycle[key] + 2
            for key in ("status", "events", "logs")
        )
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        stopped = requests.copy()
        page.wait_for_timeout(1_800)
        assert requests == stopped

        for _ in range(2):
            page.get_by_role("link", name="设置", exact=True).click()
            page.get_by_role("link", name="诊断", exact=True).click()
            expect(page.get_by_role("heading", name="服务状态", exact=True)).to_be_visible()
            page.get_by_role("link", name="今日", exact=True).click()
            expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()

        page.get_by_role("link", name="设置", exact=True).click()
        page.get_by_role("link", name="诊断", exact=True).click()
        expect(page.get_by_role("heading", name="服务状态", exact=True)).to_be_visible()
        steady = requests.copy()
        page.wait_for_timeout(3_200)
        assert all(
            2 <= requests[key] - steady[key] <= 3
            for key in ("status", "events", "logs")
        )
        assert requests["live"] == 1
        browser.close()


def test_replacement_diagnostics_ignores_late_results_and_covers_visible_states(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(reduced_motion="reduce")
        page = context.new_page()
        page.set_viewport_size({"width": 520, "height": 640})
        delayed_status = []

        def delay_first_status(route, request) -> None:
            if not delayed_status:
                delayed_status.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/status", delay_first_status)
        page.goto(f"{base_url}/#/settings/diagnostics")
        expect(page.get_by_text("正在加载诊断数据…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_status
        delayed_status[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "backend": {"ok": True, "service": "mellowday"},
                    "provider": {
                        "name": "Late Provider",
                        "configured": True,
                        "enabled": True,
                        "health": {"state": "available"},
                    },
                    "sessions": 99,
                    "pending_confirmations": 0,
                    "tools": 0,
                    "skills": 0,
                    "event_cursor": 0,
                    "log_cursor": 0,
                    "single_user": True,
                }
            ),
        )
        expect(page.get_by_text("Late Provider", exact=False)).not_to_be_visible()
        page.unroute("**/api/settings/status", delay_first_status)

        page.route(
            "**/api/logs/recent*",
            lambda route: route.fulfill(status=503, body="Unavailable"),
        )
        page.goto(f"{base_url}/#/settings/diagnostics")
        failure = page.get_by_role("alert")
        expect(failure).to_contain_text("诊断数据加载失败")
        page.unroute("**/api/logs/recent*")
        failure.get_by_role("button", name="重试", exact=True).click()
        expect(page.get_by_role("heading", name="服务状态", exact=True)).to_be_visible()

        page.get_by_label("会话", exact=True).fill("no-events-for-this-test")
        page.get_by_label("日志搜索", exact=True).fill("no-logs-for-this-test")
        page.get_by_role("button", name="刷新诊断数据", exact=True).click()
        expect(
            page.get_by_text("没有符合条件的运行事件。", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("没有符合条件的运行日志。", exact=True)
        ).to_be_visible()

        long_message = "long diagnostic line " + "x" * 1_200
        logging.getLogger("mellowday.browser_test").warning(long_message)
        page.get_by_label("日志搜索", exact=True).fill("long diagnostic line")
        page.get_by_role("button", name="刷新诊断数据", exact=True).click()
        expect(page.get_by_text(long_message, exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.diagnostics-page')).transitionDuration)"
        ) <= 0.00001
        browser.close()
