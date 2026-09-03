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


def test_replacement_life_notes_supports_the_complete_lifecycle(
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
        page.goto(f"{base_url}/#/life/notes")

        expect(page.get_by_role("navigation", name="生活二级导航")).to_be_visible()
        expect(page.get_by_text("还没有笔记。", exact=True)).to_be_visible()
        expect(
            page.get_by_text("笔记用于保存自由文本，作为生活记录独立管理。")
        ).to_be_visible()

        title = page.get_by_label("笔记标题（可选）", exact=True)
        content = page.get_by_label("笔记内容", exact=True)
        title.fill("Trip ideas")
        content.fill("Visit Kyoto\nThen take the train to Nara.")
        page.get_by_role("button", name="添加笔记", exact=True).click()
        expect(page.get_by_role("status", name="笔记状态")).to_contain_text(
            "笔记已添加"
        )
        expect(page.get_by_text("Trip ideas", exact=True)).to_be_visible()

        page.get_by_role("button", name="查看 Trip ideas").click()
        details = page.locator(".note-details")
        expect(details).to_contain_text("Visit Kyoto")
        expect(details).to_contain_text("Then take the train to Nara.")

        page.get_by_role("button", name="编辑 Trip ideas").click()
        content = page.locator(".note-form textarea")
        expect(content).to_be_focused()
        title.fill("")
        content.fill("Visit Kyoto and Nara")
        page.get_by_role("button", name="保存笔记", exact=True).click()
        expect(page.get_by_role("status", name="笔记状态")).to_contain_text(
            "笔记已保存"
        )
        expect(
            details.get_by_role("heading", name="无标题笔记", exact=True)
        ).to_be_visible()
        expect(details).to_contain_text("Visit Kyoto and Nara")

        search = page.get_by_label("搜索笔记", exact=True)
        search.fill("Nara")
        page.get_by_role("button", name="搜索", exact=True).click()
        expect(
            page.locator(".note-list-section").get_by_role(
                "heading", name="无标题笔记", exact=True
            )
        ).to_be_visible()
        search.fill("missing")
        page.get_by_role("button", name="搜索", exact=True).click()
        expect(page.get_by_text("没有匹配的笔记。", exact=True)).to_be_visible()
        search.fill("")
        page.get_by_role("button", name="搜索", exact=True).click()

        delete_button = page.get_by_role("button", name="删除 无标题笔记")
        delete_button.click()
        confirmation = page.get_by_role("dialog", name="删除笔记")
        cancel_delete = confirmation.get_by_role("button", name="取消", exact=True)
        confirm_delete = confirmation.get_by_role(
            "button", name="确认删除", exact=True
        )
        expect(cancel_delete).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(confirm_delete).to_be_focused()
        page.keyboard.press("Tab")
        expect(cancel_delete).to_be_focused()
        page.keyboard.press("Escape")
        expect(confirmation).not_to_be_visible()
        expect(delete_button).to_be_focused()
        expect(page.get_by_role("status", name="笔记状态")).to_contain_text(
            "已取消删除笔记"
        )

        delete_button.click()

        def fail_delete(route, request) -> None:
            if request.method == "DELETE":
                route.fulfill(status=503, body="Unavailable")
            else:
                route.continue_()

        page.route("**/api/settings/notes/**", fail_delete)
        confirm_delete.click()
        expect(confirmation.get_by_role("status", name="删除状态")).to_contain_text(
            "笔记删除失败"
        )
        page.unroute("**/api/settings/notes/**", fail_delete)
        confirm_delete.click()
        expect(page.get_by_role("status", name="笔记状态")).to_contain_text(
            "笔记已删除"
        )
        expect(page.get_by_text("还没有笔记。", exact=True)).to_be_visible()
        browser.close()


def test_replacement_life_notes_ignores_late_reads_and_wraps_long_content(
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
        delayed_routes = []

        def delay_note_list(route, request) -> None:
            if request.method == "GET" and "?" not in request.url:
                delayed_routes.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/notes", delay_note_list)
        page.goto(f"{base_url}/#/life/notes")
        expect(page.get_by_text("正在加载笔记…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_routes
        delayed_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"notes":[{"id":"late","title":"Late note",'
                '"content":"late content","created_at":1,"updated_at":1}]}'
            ),
        )
        expect(page.get_by_text("Late note", exact=True)).not_to_be_visible()

        page.unroute("**/api/settings/notes", delay_note_list)
        page.route(
            "**/api/settings/notes",
            lambda route, request: route.fulfill(status=503, body="Unavailable")
            if request.method == "GET"
            else route.continue_(),
        )
        page.goto(f"{base_url}/#/life/notes")
        expect(page.get_by_role("alert")).to_contain_text("笔记加载失败")
        page.unroute("**/api/settings/notes")
        page.get_by_role("button", name="重试", exact=True).click()
        expect(page.get_by_text("还没有笔记。", exact=True)).to_be_visible()

        page.get_by_role("button", name="添加笔记", exact=True).click()
        expect(page.get_by_role("status", name="笔记状态")).to_contain_text(
            "请输入笔记内容"
        )
        content = page.get_by_label("笔记内容", exact=True)
        expect(content).to_be_focused()

        long_content = "A" * 600
        page.get_by_label("笔记标题（可选）", exact=True).fill("Long note")
        content.fill(long_content)
        page.get_by_role("button", name="添加笔记", exact=True).click()
        page.get_by_role("button", name="查看 Long note").click()
        expect(page.locator(".note-content")).to_have_text(long_content)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()
