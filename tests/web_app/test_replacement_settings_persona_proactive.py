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


def test_replacement_settings_persona_and_proactive_chat_complete_lifecycle(
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
        page.goto(f"{base_url}/#/settings")
        expect(page.get_by_role("heading", name="外观", exact=True)).to_be_visible()

        page.goto(f"{base_url}/#/settings/persona")
        expect(page.get_by_role("navigation", name="设置二级导航")).to_be_visible()
        expect(
            page.get_by_role("heading", name="人格设定", exact=True, level=1)
        ).to_be_visible()
        expect(
            page.get_by_text(
                "这些内容只影响聊天表达，不影响设置、记录、权限、日志和诊断中的文字。"
            )
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        name = page.get_by_label("名称", exact=True)
        name.fill("")
        name.press("Enter")
        expect(page.get_by_role("status", name="人格设定状态")).to_contain_text(
            "请输入名称"
        )
        expect(name).to_be_focused()
        name.fill("Luma")
        page.get_by_role("button", name="保存人格设定", exact=True).click()
        expect(page.get_by_role("status", name="人格设定状态")).to_contain_text(
            "人格设定已保存"
        )

        page.get_by_role("link", name="主动聊天", exact=True).click()
        expect(page).to_have_url(f"{base_url}/#/settings/proactive-chat")
        expect(
            page.get_by_role("heading", name="主动聊天", exact=True, level=1)
        ).to_be_visible()
        expect(
            page.get_by_text("评估过程不会创建或修改记忆和生活记录。", exact=False)
        ).to_be_visible()
        style = page.get_by_label("主动聊天风格", exact=True)
        style.fill("")
        page.get_by_role("button", name="保存主动聊天设置", exact=True).click()
        expect(
            page.get_by_role("status", name="主动聊天设置状态")
        ).to_contain_text("请输入主动聊天风格")
        expect(style).to_be_focused()

        page.get_by_label("启用主动聊天", exact=True).check()
        page.get_by_label("安静时段开始", exact=True).fill("22:00")
        page.get_by_label("安静时段结束", exact=True).fill("08:00")
        page.get_by_label("冷却时间（秒）", exact=True).fill("60")
        page.get_by_label("每日上限", exact=True).fill("2")
        style.fill("low-pressure check-ins")

        def fail_save(route, request) -> None:
            if request.method == "PUT":
                route.fulfill(status=503, body="Unavailable")
            else:
                route.continue_()

        page.route("**/api/settings/proactive-chat", fail_save)
        page.get_by_role("button", name="保存主动聊天设置", exact=True).click()
        expect(
            page.get_by_role("status", name="主动聊天设置状态")
        ).to_contain_text("主动聊天设置保存失败")
        expect(style).to_have_value("low-pressure check-ins")
        page.unroute("**/api/settings/proactive-chat", fail_save)

        page.get_by_role("button", name="保存主动聊天设置", exact=True).click()
        expect(
            page.get_by_role("status", name="主动聊天设置状态")
        ).to_contain_text("主动聊天设置已保存")

        with Client(base_url=base_url) as client:
            settings = client.get("/api/settings/proactive-chat").json()["settings"]
            persona = client.get("/api/settings/persona").json()["persona"]
        assert settings == {
            "enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "08:00",
            "cooldown_seconds": 60,
            "daily_limit": 2,
            "proactive_chat_style": "low-pressure check-ins",
        }
        assert persona["name"] == "Luma"
        assert persona["proactive_chat_style"] == "low-pressure check-ins"

        page.get_by_role("link", name="人格设定", exact=True).click()
        expect(page.get_by_label("名称", exact=True)).to_have_value("Luma")
        expect(page.get_by_label("主动聊天风格", exact=True)).to_have_value(
            "low-pressure check-ins"
        )
        browser.close()


def test_replacement_settings_discards_route_obsolete_load_and_save(
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
        delayed_loads = []

        def delay_persona_load(route, request) -> None:
            if request.method == "GET":
                delayed_loads.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/persona", delay_persona_load)
        page.goto(f"{base_url}/#/settings/persona")
        expect(page.get_by_text("正在加载人格设定…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_loads
        delayed_loads[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "persona": {
                        "name": "Late Persona",
                        "identity": "late",
                        "character": "late",
                        "speaking_style": "late",
                        "relationship_framing": "late",
                        "conversational_boundaries": "late",
                        "proactive_chat_style": "late",
                    }
                }
            ),
        )
        expect(page.get_by_text("Late Persona", exact=True)).not_to_be_visible()
        page.unroute("**/api/settings/persona", delay_persona_load)

        page.goto(f"{base_url}/#/settings/persona")
        expect(page.get_by_label("名称", exact=True)).to_be_visible()
        delayed_saves = []

        def delay_persona_save(route, request) -> None:
            if request.method == "PUT":
                delayed_saves.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/persona", delay_persona_save)
        page.get_by_label("名称", exact=True).fill("Unsaved Persona")
        page.get_by_role("button", name="保存人格设定", exact=True).click()
        expect(page.get_by_role("button", name="正在保存…", exact=True)).to_be_disabled()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_saves
        delayed_saves[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "persona": {
                        "name": "Unsaved Persona",
                        "identity": "late",
                        "character": "late",
                        "speaking_style": "late",
                        "relationship_framing": "late",
                        "conversational_boundaries": "late",
                        "proactive_chat_style": "late",
                    }
                }
            ),
        )
        expect(page.get_by_text("人格设定已保存。", exact=True)).not_to_be_visible()
        page.unroute("**/api/settings/persona", delay_persona_save)

        page.route(
            "**/api/settings/proactive-chat",
            lambda route: route.fulfill(status=503, body="Unavailable"),
        )
        page.goto(f"{base_url}/#/settings/proactive-chat")
        load_failure = page.get_by_role("alert")
        expect(load_failure).to_contain_text("主动聊天设置加载失败")
        page.unroute("**/api/settings/proactive-chat")
        load_failure.get_by_role("button", name="重试", exact=True).click()
        expect(page.get_by_label("启用主动聊天", exact=True)).to_be_visible()
        browser.close()
