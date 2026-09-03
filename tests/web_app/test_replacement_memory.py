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

from mellowday.agent_core import ProviderReply, ProviderRequest, ToolCall
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


class MemoryProvider:
    name = "memory-replacement-script"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        if request.tool_results:
            return ProviderReply(content="Saved.")
        return ProviderReply(
            tool_calls=(
                ToolCall(
                    "remember-replacement",
                    "memory_remember",
                    {
                        "content": "I prefer concise replies.",
                        "kind": "preference",
                        "evidence": "Remember that I prefer concise replies.",
                    },
                ),
            )
        )


def seed_memory(base_url: str) -> None:
    with Client(base_url=base_url) as client:
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": "main",
                "content": "Remember that I prefer concise replies.",
            },
        )
    assert response.status_code == 200


def test_replacement_memory_supports_inspect_edit_search_and_confirmed_delete(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=MemoryProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        seed_memory(base_url)
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 520, "height": 640})
        page.goto(f"{base_url}/#/memory")

        expect(page.get_by_role("heading", name="记忆管理", exact=True)).to_be_visible()
        expect(page.get_by_text("I prefer concise replies.", exact=True)).to_be_visible()
        expect(
            page.get_by_text(
                "任务、提醒、日历事件、笔记和对话历史保留在各自的产品区域。"
            )
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        body_text = page.locator("body").inner_text().lower()
        for excluded in ("embedding", "similarity", "knowledge graph", "tag"):
            assert excluded not in body_text

        page.get_by_role("button", name="查看 I prefer concise replies.").click()
        details = page.locator(".memory-details")
        expect(details).to_contain_text("偏好")
        expect(details).to_contain_text("由你明确保存")

        page.get_by_role("button", name="编辑 I prefer concise replies.").click()
        content = page.locator(".memory-editor textarea")
        expect(content).to_be_focused()
        content.fill("")
        page.get_by_role("button", name="保存记忆", exact=True).click()
        expect(page.get_by_role("status", name="记忆状态")).to_contain_text(
            "记忆内容不能为空"
        )
        expect(content).to_be_focused()
        content.fill("I prefer detailed replies.")
        page.locator(".memory-editor select").select_option("important")
        page.get_by_role("button", name="保存记忆", exact=True).click()
        expect(page.get_by_role("status", name="记忆状态")).to_contain_text(
            "记忆已保存"
        )
        expect(page.get_by_text("I prefer detailed replies.", exact=True)).to_be_visible()

        search = page.get_by_label("搜索记忆", exact=True)
        search.fill("missing")
        page.get_by_role("button", name="搜索", exact=True).click()
        expect(page.get_by_text("没有匹配的记忆。", exact=True)).to_be_visible()
        search.fill("")
        page.get_by_role("button", name="搜索", exact=True).click()

        delete_button = page.get_by_role("button", name="删除 I prefer detailed replies.")
        delete_button.click()
        confirmation = page.get_by_role("dialog", name="删除记忆")
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
        expect(page.get_by_role("status", name="记忆状态")).to_contain_text(
            "已取消删除记忆"
        )

        delete_button.click()

        def fail_delete(route, request) -> None:
            if request.method == "DELETE":
                route.fulfill(status=503, body="Unavailable")
            else:
                route.continue_()

        page.route("**/api/settings/memories/**", fail_delete)
        confirm_delete.click()
        expect(confirmation.get_by_role("status", name="删除状态")).to_contain_text(
            "记忆删除失败"
        )
        page.unroute("**/api/settings/memories/**", fail_delete)
        confirm_delete.click()
        expect(page.get_by_role("status", name="记忆状态")).to_contain_text(
            "记忆已删除"
        )
        expect(page.get_by_text("还没有记忆。", exact=True)).to_be_visible()
        browser.close()


def test_replacement_memory_ignores_obsolete_search_and_route_reads(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=MemoryProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 881, "height": 780})
        delayed_routes = []

        def delay_initial(route, request) -> None:
            if request.method == "GET":
                delayed_routes.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/memories?q=", delay_initial)
        page.goto(f"{base_url}/#/memory")
        expect(page.get_by_text("正在加载记忆…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_routes
        delayed_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"memories":[{"id":"late","content":"Late Memory",'
                '"kind":"fact","provenance":"explicit",'
                '"source_conversation_id":"main","created_at":1,"updated_at":1}]}'
            ),
        )
        expect(page.get_by_text("Late Memory", exact=True)).not_to_be_visible()
        page.unroute("**/api/settings/memories?q=", delay_initial)

        page.goto(f"{base_url}/#/memory")
        expect(page.get_by_text("还没有记忆。", exact=True)).to_be_visible()
        obsolete_routes = []

        def answer_search(route, request) -> None:
            if "q=first" in request.url:
                obsolete_routes.append(route)
            elif "q=second" in request.url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"memories":[{"id":"new","content":"Newest result",'
                        '"kind":"important","provenance":"automatic",'
                        '"source_conversation_id":null,"created_at":2,"updated_at":2}]}'
                    ),
                )
            else:
                route.continue_()

        page.route("**/api/settings/memories?*", answer_search)
        search = page.get_by_label("搜索记忆", exact=True)
        search.fill("first")
        page.get_by_role("button", name="搜索", exact=True).click()
        expect(page.get_by_text("正在加载记忆…", exact=True)).to_be_visible()
        search.fill("second")
        page.get_by_role("button", name="搜索", exact=True).click()
        expect(page.get_by_text("Newest result", exact=True)).to_be_visible()
        assert obsolete_routes
        obsolete_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"memories":[{"id":"old","content":"Obsolete result",'
                '"kind":"fact","provenance":"explicit",'
                '"source_conversation_id":null,"created_at":1,"updated_at":1}]}'
            ),
        )
        expect(page.get_by_text("Newest result", exact=True)).to_be_visible()
        expect(page.get_by_text("Obsolete result", exact=True)).not_to_be_visible()
        page.unroute("**/api/settings/memories?*", answer_search)

        page.route(
            "**/api/settings/memories?*",
            lambda route: route.fulfill(status=503, body="Unavailable"),
        )
        search.fill("failure")
        page.get_by_role("button", name="搜索", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("记忆加载失败")
        page.unroute("**/api/settings/memories?*")
        page.get_by_role("button", name="重试", exact=True).click()
        expect(page.get_by_text("没有匹配的记忆。", exact=True)).to_be_visible()
        browser.close()
