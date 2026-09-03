import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from playwright.sync_api import expect, sync_playwright

from mellowday.agent_core import Skill, Tool
from mellowday.agent_core.openai_compatible import ProviderTransportResponse
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


def test_replacement_provider_and_capability_settings_complete_lifecycle(
    tmp_path: Path,
) -> None:
    loads: list[str] = []

    async def read_status(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        return {"conversation_id": conversation_id, **arguments}

    class ValidTransport:
        async def request(
            self,
            _method: str,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object] | None,
            timeout: float,
        ) -> ProviderTransportResponse:
            return ProviderTransportResponse(
                status_code=200, payload={"data": [{"id": "first-model"}]}
            )

    app = create_app(
        tools=(
            Tool(
                name="status_read",
                description="Read local status.",
                input_schema={"type": "object", "properties": {}},
                executor=read_status,
                permission_requirements=("status:read",),
                side_effect="none",
                risk="low",
            ),
        ),
        skills=(
            Skill(
                name="plain_language",
                description="Explain status in plain language.",
                instruction_loader=(
                    lambda: loads.append("loaded") or "Use plain language."
                ),
            ),
        ),
        skill_state_path=None,
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
        provider_transport=ValidTransport(),
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 520, "height": 640})
        delayed_loads = []

        def delay_initial_load(route, request) -> None:
            if request.method == "GET":
                delayed_loads.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/providers", delay_initial_load)
        page.goto(f"{base_url}/#/settings/providers")
        expect(page.get_by_text("正在加载模型提供方…", exact=True)).to_be_visible()
        navigation = page.get_by_role("navigation", name="设置二级导航")
        assert navigation.evaluate("element => element.scrollWidth > element.clientWidth")
        assert delayed_loads
        delayed_loads[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"providers": []}),
        )
        page.unroute("**/api/settings/providers", delay_initial_load)
        expect(page.get_by_text("尚未配置模型提供方。", exact=True)).to_be_visible()

        page.get_by_role("button", name="添加提供方", exact=True).click()
        expect(page.get_by_role("status", name="模型提供方状态")).to_contain_text(
            "请输入提供方名称"
        )
        expect(page.get_by_label("提供方名称", exact=True)).to_be_focused()

        page.get_by_label("提供方名称", exact=True).fill("Local model")
        page.get_by_label("基础地址", exact=True).fill("http://localhost:9000/v1")
        page.get_by_label("模型", exact=True).fill("first-model")
        page.get_by_label("API 密钥", exact=True).fill("local-secret")
        page.get_by_label("超时时间（秒）", exact=True).fill("12")
        page.get_by_label("最大重试次数", exact=True).fill("1")
        page.get_by_role("button", name="添加提供方", exact=True).click()
        expect(page.get_by_role("status", name="模型提供方状态")).to_contain_text(
            "Local model 已保存"
        )
        expect(page.get_by_text("••••cret", exact=True)).to_be_visible()
        expect(page.get_by_label("API 密钥", exact=True)).to_have_value("")
        assert "local-secret" not in page.locator("body").inner_text()

        page.get_by_role("button", name="选择 Local model").focus()
        expect(page.get_by_role("button", name="选择 Local model")).to_be_focused()
        page.get_by_role("button", name="选择 Local model").press("Enter")
        expect(page.get_by_text("当前使用", exact=True)).to_be_visible()
        page.get_by_role("button", name="验证 Local model").click()
        expect(page.get_by_role("status", name="模型提供方状态")).to_contain_text(
            "Local model 验证通过"
        )

        page.get_by_role("button", name="编辑 Local model").click()
        expect(page.get_by_label("提供方名称", exact=True)).to_be_focused()
        expect(page.get_by_label("API 密钥", exact=True)).to_have_value("")
        page.get_by_label("模型", exact=True).fill("edited-model")
        page.get_by_role("button", name="保存提供方", exact=True).click()
        expect(page.get_by_text("edited-model", exact=False)).to_be_visible()
        expect(page.get_by_text("••••cret", exact=True)).to_be_visible()

        def fail_enablement(route, request) -> None:
            route.fulfill(status=503, body="Unavailable")

        enabled = page.get_by_role("checkbox", name="停用 Local model")
        page.route("**/api/settings/providers/*/enabled", fail_enablement)
        enabled.click()
        expect(page.get_by_role("status", name="模型提供方状态")).to_contain_text(
            "Local model 更新失败"
        )
        expect(enabled).to_be_checked()
        page.unroute("**/api/settings/providers/*/enabled", fail_enablement)
        enabled.focus()
        enabled.press("Space")
        expect(page.get_by_text("已停用", exact=True)).to_be_visible()

        capability_link = page.get_by_role("link", name="能力", exact=True)
        capability_link.focus()
        capability_link.press("Enter")
        expect(page).to_have_url(
            f"{base_url}/#/settings/capabilities"
        )
        expect(page.get_by_text("status_read", exact=True)).to_be_visible()
        expect(page.get_by_text("status:read", exact=True)).to_be_visible()
        expect(page.get_by_text("plain_language", exact=True)).to_be_visible()
        skill_enablement = page.get_by_role(
            "checkbox", name="停用 plain_language 技能"
        )
        skill_enablement.focus()
        skill_enablement.press("Space")
        expect(page.get_by_role("status", name="能力状态")).to_contain_text(
            "plain_language 已停用"
        )
        assert loads == []
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_replacement_provider_and_capability_pages_ignore_obsolete_work(
    tmp_path: Path,
) -> None:
    app = create_app(
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 881, "height": 780})
        delayed_provider_loads = []
        capability_loads = 0
        fail_next_capability_load = True

        def delay_provider_load(route, request) -> None:
            if request.method == "GET":
                delayed_provider_loads.append(route)
            else:
                route.continue_()

        def observe_capability_load(route, request) -> None:
            nonlocal capability_loads, fail_next_capability_load
            capability_loads += 1
            if fail_next_capability_load:
                fail_next_capability_load = False
                route.fulfill(status=503, body="Unavailable")
            else:
                route.continue_()

        page.route("**/api/settings/providers", delay_provider_load)
        page.route("**/api/settings/capabilities", observe_capability_load)
        page.goto(f"{base_url}/#/settings/providers")
        expect(page.get_by_text("正在加载模型提供方…", exact=True)).to_be_visible()
        page.get_by_role("link", name="能力", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("能力加载失败")
        assert delayed_provider_loads
        delayed_provider_loads[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "providers": [
                        {
                            "id": "late-provider",
                            "name": "Late Provider",
                            "base_url": "http://late.invalid/v1",
                            "model": "late-model",
                            "api_key": "••••late",
                            "timeout_seconds": 60,
                            "max_retries": 2,
                            "enabled": True,
                            "selected": False,
                        }
                    ]
                }
            ),
        )
        expect(page.get_by_text("Late Provider", exact=True)).not_to_be_visible()
        page.unroute("**/api/settings/providers", delay_provider_load)

        page.get_by_role("alert").get_by_role("button", name="重试").click()
        expect(page.get_by_role("heading", name="能力", exact=True, level=1)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        page.wait_for_timeout(250)
        assert capability_loads == 2
        browser.close()
