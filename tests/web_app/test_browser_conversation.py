import asyncio
import socket
import threading
import time
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from httpx import Client
from playwright.sync_api import expect, sync_playwright

from mellowday.agent_core import (
    FakeProvider,
    ProviderReply,
    ProviderRequest,
    Tool,
    ToolCall,
)
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


def test_react_replacement_renders_from_the_python_static_host(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        console_errors: list[str] = []
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(f"{base_url}/")

        expect(
            page.get_by_role("heading", name="我在这里，陪你梳理今天。")
        ).to_have_count(0)
        expect(page.get_by_role("heading", name="今天，慢慢来")).to_be_visible()
        expect(
            page.get_by_text("已加载存储会话。", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("navigation", name="产品区域")).to_be_visible()
        assert console_errors == []
        browser.close()


def test_replacement_app_shell_routes_follow_browser_history(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/#/settings")

        expect(page).to_have_url(f"{base_url}/#/settings/appearance")
        expect(page.get_by_role("heading", name="外观")).to_be_visible()
        expect(page.get_by_role("link", name="设置", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(
            page.get_by_role("link", name="人格设定", exact=True)
        ).to_be_visible()

        page.get_by_role("link", name="生活", exact=True).click()
        expect(page).to_have_url(f"{base_url}/#/life/tasks")
        expect(
            page.get_by_role("heading", name="任务", exact=True)
        ).to_be_visible()

        page.get_by_role("link", name="记忆", exact=True).click()
        expect(page).to_have_url(f"{base_url}/#/memory")
        expect(page.get_by_role("heading", name="记忆管理")).to_be_visible()

        page.go_back()
        expect(page).to_have_url(f"{base_url}/#/life/tasks")
        page.go_forward()
        expect(page).to_have_url(f"{base_url}/#/memory")

        page.goto(f"{base_url}/#/unknown")
        expect(page).to_have_url(f"{base_url}/#/conversation")
        browser.close()


def test_replacement_appearance_popover_and_settings_share_persisted_state(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/#/conversation")

        expect(page.locator("html")).to_have_attribute("data-theme", "sky")
        expect(page.get_by_role("button", name="外观，当前主题：晴空")).to_have_count(0)
        page.get_by_role("link", name="设置", exact=True).click()
        appearance_page = page.get_by_label("外观设置")

        appearance_page.get_by_role("radio", name="简约").click()
        appearance_page.get_by_role("slider", name="强调色色相").fill("286")
        appearance_page.get_by_role("slider", name="背景亮度").fill("91")
        expect(page.locator("html")).to_have_attribute("data-theme", "minimal")
        expect(page.locator("[data-theme-decoration]")).to_have_count(0)
        expect(appearance_page.get_by_role("radio", name="简约")).to_have_attribute(
            "aria-checked", "true"
        )
        expect(appearance_page.get_by_role("slider", name="强调色色相")).to_have_value("286")
        expect(appearance_page.get_by_role("slider", name="背景亮度")).to_have_value("91")

        page.reload()
        appearance_page = page.get_by_label("外观设置")
        expect(page.locator("html")).to_have_attribute("data-theme", "minimal")
        expect(appearance_page.get_by_role("slider", name="强调色色相")).to_have_value("286")
        appearance_page.get_by_role("button", name="重置简约外观").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "minimal")
        expect(appearance_page.get_by_role("slider", name="强调色色相")).to_have_value("211")
        expect(appearance_page.get_by_role("slider", name="背景亮度")).to_have_value("97")
        browser.close()


def test_replacement_appearance_popover_meets_keyboard_and_sizing_contract(
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
        page.goto(f"{base_url}/#/settings/appearance")

        appearance_page = page.get_by_label("外观设置")
        box = appearance_page.bounding_box()
        assert box is not None
        assert box["width"] <= 496
        assert box["x"] >= 12
        assert box["x"] + box["width"] <= 508

        sky = appearance_page.get_by_role("radio", name="晴空")
        sakura = appearance_page.get_by_role("radio", name="樱粉")
        minimal = appearance_page.get_by_role("radio", name="简约")
        expect(sky).to_have_attribute("tabindex", "0")
        expect(sakura).to_have_attribute("tabindex", "-1")
        sky.focus()
        page.keyboard.press("ArrowRight")
        expect(sakura).to_be_focused()
        expect(page.locator("html")).to_have_attribute("data-theme", "sakura")
        page.keyboard.press("End")
        expect(minimal).to_be_focused()
        expect(page.locator("html")).to_have_attribute("data-theme", "minimal")
        page.keyboard.press("Home")
        expect(sky).to_be_focused()
        expect(page.locator("html")).to_have_attribute("data-theme", "sky")

        night = appearance_page.get_by_role("radio", name="夜色")
        night.focus()
        expect(night).to_be_focused()
        night.press("Enter")
        expect(page.locator("html")).to_have_attribute("data-theme", "night")
        browser.close()


def test_replacement_requests_only_the_selected_theme_decorations(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for theme in ("sky", "sakura", "mint", "night", "minimal"):
            context = browser.new_context()
            context.add_init_script(
                script=f"""
                window.localStorage.setItem("mellowday.appearance", JSON.stringify({{
                  version: 1,
                  theme: "{theme}",
                  minimal: {{accentHue: 211, backgroundLightness: 97}},
                }}));
                """
            )
            page = context.new_page()
            responses: list[tuple[str, int]] = []
            page.on(
                "response",
                lambda response: responses.append((response.url, response.status))
                if "/runtime/themes/" in response.url
                else None,
            )
            page.goto(f"{base_url}/")
            expect(page.locator("html")).to_have_attribute("data-theme", theme)
            if theme != "minimal":
                page.wait_for_function(
                    """() => [...document.querySelectorAll(
                      '[data-theme-decoration] img'
                    )].every((image) => image.complete)"""
                )

            decoration_responses = [
                (url.rsplit("/", 1)[-1], status) for url, status in responses
            ]
            if theme == "minimal":
                assert decoration_responses == []
                expect(page.locator("[data-theme-decoration]")).to_have_count(0)
            else:
                assert sorted(decoration_responses) == [
                    (f"{theme}-corner.webp", 200),
                    (f"{theme}-emblem.webp", 200),
                    (f"{theme}-motif.svg", 200),
                ]
                decoration = page.locator("[data-theme-decoration]")
                expect(decoration).to_have_count(1)
                expect(decoration).to_have_attribute("aria-hidden", "true")
                expect(decoration).to_have_css("pointer-events", "none")
            context.close()
        browser.close()


def test_replacement_themes_preserve_content_geometry_with_reduced_motion(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            stored = client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Geometry fixture"},
            )
        assert stored.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1200, "height": 780},
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.goto(f"{base_url}/")
        workspace = page.locator(".conversation-workspace")
        baseline_box = workspace.bounding_box()
        baseline_type = page.locator(".message p").first.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return [style.fontFamily, style.fontSize, style.lineHeight];
            }"""
        )
        assert baseline_box is not None

        for theme, label in (
            ("sky", "晴空"),
            ("sakura", "樱粉"),
            ("mint", "薄荷"),
            ("night", "夜色"),
            ("minimal", "简约"),
        ):
            page.goto(f"{base_url}/#/settings/appearance")
            appearance_page = page.get_by_label("外观设置")
            appearance_page.get_by_role("radio", name=label).click()
            expect(page.locator("html")).to_have_attribute("data-theme", theme)
            control_contrasts = appearance_page.locator(
                ".theme-option[aria-checked='false']"
            ).evaluate_all(
                """elements => {
                  const canvas = document.createElement('canvas');
                  canvas.width = 1;
                  canvas.height = 1;
                  const context = canvas.getContext('2d', {willReadFrequently: true});
                  if (context === null) return [];
                  const color = value => {
                    context.clearRect(0, 0, 1, 1);
                    context.fillStyle = value;
                    context.fillRect(0, 0, 1, 1);
                    return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3);
                  };
                  const luminance = channels => channels
                    .map(channel => channel / 255)
                    .map(channel => channel <= 0.04045
                      ? channel / 12.92
                      : ((channel + 0.055) / 1.055) ** 2.4)
                    .reduce((sum, channel, index) =>
                      sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
                  return elements.map(element => {
                    const style = getComputedStyle(element);
                    const border = luminance(color(style.borderTopColor));
                    const background = luminance(color(style.backgroundColor));
                    return (Math.max(border, background) + 0.05)
                      / (Math.min(border, background) + 0.05);
                  });
                }"""
            )
            assert control_contrasts
            assert min(control_contrasts) >= 3

            page.goto(f"{base_url}/#/conversation")
            page.reload()
            expect(page.get_by_role("heading", name="Geometry fixture")).to_be_visible()
            current_box = workspace.bounding_box()
            assert current_box is not None
            for dimension in ("x", "y", "width", "height"):
                assert abs(current_box[dimension] - baseline_box[dimension]) <= 1
            assert page.locator(".message p").first.evaluate(
                """element => {
                  const style = getComputedStyle(element);
                  return [style.fontFamily, style.fontSize, style.lineHeight];
                }"""
            ) == baseline_type
            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth"
            )

        assert page.evaluate(
            "matchMedia('(prefers-reduced-motion: reduce)').matches"
        )
        assert page.locator(".shell-layout").evaluate(
            "element => parseFloat(getComputedStyle(element).transitionDuration) <= 0.00001"
        )
        context.close()
        browser.close()


def test_narrow_recent_conversation_drawer_contains_and_restores_focus(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            stored = client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Drawer fixture"},
            )
        assert stored.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 880, "height": 780})
        page.goto(f"{base_url}/")

        trigger = page.get_by_role("button", name="最近对话")
        trigger.click()
        drawer = page.get_by_role("dialog", name="最近对话")
        expect(drawer).to_be_visible()
        expect(drawer).to_have_attribute("aria-modal", "true")
        assert page.locator("[data-shell-content]").evaluate(
            "element => element.inert"
        )

        page.keyboard.press("Tab")
        assert drawer.evaluate("element => element.contains(document.activeElement)")
        page.keyboard.press("Shift+Tab")
        assert drawer.evaluate("element => element.contains(document.activeElement)")

        page.keyboard.press("Escape")
        expect(drawer).not_to_be_visible()
        expect(trigger).to_be_focused()

        trigger.click()
        page.get_by_role("button", name="关闭最近对话").click()
        expect(trigger).to_be_focused()
        browser.close()


def test_replacement_window_controls_require_desktop_capability(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser_page = browser.new_page()
        browser_page.goto(f"{base_url}/")
        expect(
            browser_page.get_by_role("button", name="最小化窗口")
        ).to_have_count(0)

        desktop_page = browser.new_page()
        desktop_page.add_init_script(
            """
            window.__desktopAction = "";
            window.mellowdayDesktop = {
              windowControls: {
                minimize: () => { window.__desktopAction = "minimize"; },
                toggleMaximize: () => { window.__desktopAction = "maximize"; },
                close: () => { window.__desktopAction = "close"; },
              },
            };
            """
        )
        desktop_page.goto(f"{base_url}/")
        minimize = desktop_page.get_by_role("button", name="最小化窗口")
        expect(desktop_page.locator(".title-bar")).to_have_css(
            "-webkit-app-region", "drag"
        )
        expect(minimize).to_have_css("-webkit-app-region", "no-drag")
        minimize.click()
        assert desktop_page.evaluate("window.__desktopAction") == "minimize"
        expect(
            desktop_page.get_by_role("button", name="切换最大化窗口")
        ).to_be_visible()
        expect(desktop_page.get_by_role("button", name="关闭窗口")).to_be_visible()
        browser.close()


def test_replacement_app_shell_restores_wide_navigation_without_overflow(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/")
        navigation = page.get_by_role("navigation", name="产品区域")
        workspace = page.locator(".conversation-workspace")

        assert round(navigation.bounding_box()["width"]) == 244
        assert round(workspace.bounding_box()["width"]) == 820
        page.get_by_role("button", name="收起导航").click()
        expect(page.locator(".app-frame")).to_have_attribute(
            "data-wide-navigation", "dock"
        )
        page.wait_for_timeout(250)
        assert round(navigation.bounding_box()["width"]) == 82
        assert round(workspace.bounding_box()["width"]) == 820

        page.set_viewport_size({"width": 880, "height": 780})
        page.wait_for_timeout(250)
        expect(page.locator(".primary-link")).to_have_count(5)
        for link in page.locator(".primary-link").all():
            expect(link).to_be_visible()
        expect(page.get_by_role("button", name="展开导航")).not_to_be_visible()
        assert round(navigation.bounding_box()["height"]) == 58
        assert round(workspace.bounding_box()["width"]) == 856

        page.set_viewport_size({"width": 881, "height": 780})
        page.wait_for_timeout(250)
        assert round(navigation.bounding_box()["width"]) == 82
        assert round(workspace.bounding_box()["width"]) == 577
        page.get_by_role("button", name="展开导航").click()
        page.wait_for_timeout(250)
        assert round(workspace.bounding_box()["width"]) == 577
        page.get_by_role("button", name="收起导航").click()

        page.set_viewport_size({"width": 521, "height": 860})
        assert round(workspace.bounding_box()["width"]) == 497
        page.set_viewport_size({"width": 520, "height": 640})
        assert round(workspace.bounding_box()["width"]) == 496

        for width, height in (
            (1200, 780),
            (881, 780),
            (880, 780),
            (521, 860),
            (520, 640),
        ):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(50)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth"
            ), f"horizontal overflow at {width}x{height}"

        page.set_viewport_size({"width": 1200, "height": 780})
        page.reload()
        page.wait_for_timeout(250)
        assert round(navigation.bounding_box()["width"]) == 82
        browser.close()


def test_production_key_layouts_hold_at_dpr_two(tmp_path: Path) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for theme, width, height in (
            ("sky", 1200, 780),
            ("minimal", 520, 640),
        ):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
                reduced_motion="reduce",
            )
            context.add_init_script(
                script=f"""
                window.localStorage.setItem("mellowday.appearance", JSON.stringify({{
                  version: 1,
                  theme: "{theme}",
                  minimal: {{accentHue: 211, backgroundLightness: 97}},
                }}));
                """
            )
            page = context.new_page()
            page.goto(f"{base_url}/")
            expect(page.locator("html")).to_have_attribute("data-theme", theme)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth"
            )
            if theme == "sky":
                corner = page.locator('img[src$="sky-corner.webp"]')
                corner.wait_for(state="visible")
                assert corner.evaluate(
                    "image => image.naturalWidth >= "
                    "image.getBoundingClientRect().width * window.devicePixelRatio"
                )
            else:
                expect(page.locator("[data-theme-decoration]")).to_have_count(0)
            context.close()
        browser.close()


def test_replacement_conversation_workspace_keeps_composer_near_window_bottom(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/")

        for width, height in ((1200, 780), (520, 640)):
            page.set_viewport_size({"width": width, "height": height})
            composer = page.get_by_role("textbox", name="消息").bounding_box()
            assert composer is not None
            assert composer["y"] + composer["height"] >= height - 100

        browser.close()


def test_wide_dock_keeps_recent_conversations_reachable(tmp_path: Path) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/")
        page.get_by_role("button", name="收起导航").click()

        trigger = page.get_by_role("button", name="最近对话")
        expect(trigger).to_be_visible()
        trigger.click()
        expect(page.get_by_role("dialog", name="最近对话")).to_be_visible()
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        browser.close()


def test_selecting_a_recent_conversation_returns_to_the_conversation_surface(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            first = client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "First fixture"},
            )
            second = client.post(
                "/api/chat",
                json={
                    "conversation_id": "project-internal-id",
                    "content": "Second conversation fixture",
                },
            )
        assert first.status_code == 200
        assert second.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/#/today")
        recent = page.locator(".recent-rail .recent-conversation-select")
        expect(recent.first).to_contain_text("Second conversation fixture")
        assert all(
            "project-internal-id" not in item for item in recent.all_inner_texts()
        )
        recent.first.click()

        expect(page).to_have_url(f"{base_url}/#/conversation")
        expect(
            page.get_by_label("会话记录").get_by_text(
                "Second conversation fixture", exact=True
            )
        ).to_be_visible()
        browser.close()


def test_recent_conversation_controls_rename_cancel_and_delete_from_the_drawer(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            created = client.post(
                "/api/chat",
                json={"conversation_id": "planning", "content": "Plan the week"},
            )
        assert created.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/#/conversation")
        recent = page.get_by_role("region", name="最近对话")

        recent.get_by_role("button", name="编辑“Plan the week”的标题").click()
        title = recent.get_by_role("textbox", name="对话标题")
        title.fill("暂不保存")
        recent.get_by_role("button", name="取消编辑").click()
        expect(recent.get_by_text("Plan the week", exact=True)).to_be_visible()

        recent.get_by_role("button", name="编辑“Plan the week”的标题").click()
        title.fill("周计划")
        recent.get_by_role("button", name="保存标题").click()
        expect(page.get_by_role("heading", name="周计划")).to_be_visible()
        page.reload()
        expect(page.get_by_role("heading", name="周计划")).to_be_visible()

        page.set_viewport_size({"width": 880, "height": 780})
        page.get_by_role("button", name="最近对话").click()
        drawer = page.get_by_role("dialog", name="最近对话")
        drawer.get_by_role("button", name="删除“周计划”").click()
        drawer.get_by_role("button", name="取消删除").click()
        expect(drawer.get_by_text("周计划", exact=True)).to_be_visible()
        drawer.get_by_role("button", name="删除“周计划”").click()
        drawer.get_by_role("button", name="确认删除“周计划”").click()

        expect(page.get_by_role("dialog", name="最近对话")).to_have_count(0)
        expect(page.get_by_role("heading", name="今天，慢慢来")).to_be_visible()
        with Client(base_url=base_url) as client:
            assert client.get("/api/conversations/planning").status_code == 404
        browser.close()


def test_recent_conversation_delete_refills_the_limit_and_restores_focus(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            for index in range(21):
                created = client.post(
                    "/api/chat",
                    json={
                        "conversation_id": f"conversation-{index:02d}",
                        "content": f"Conversation {index:02d}",
                    },
                )
                assert created.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 780})
        page.goto(f"{base_url}/#/conversation")
        recent = page.get_by_role("region", name="最近对话")
        entries = recent.locator(".recent-conversation-item")
        expect(entries).to_have_count(20)

        deleted = entries.nth(1)
        deleted.locator(".recent-conversation-actions button").nth(1).click()
        deleted.locator(".recent-delete-confirm").click()

        expect(entries).to_have_count(20)
        expect(recent.locator(".recent-conversation-select:focus")).to_have_count(1)
        browser.close()


def test_react_replacement_loads_history_and_appends_one_live_reminder(
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
        with Client(base_url=base_url) as client:
            stored = client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "Stored replacement tracer",
                },
            )
        assert stored.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        live_requests: list[str] = []
        page.on(
            "request",
            lambda request: live_requests.append(request.url)
            if "/api/conversations/main/live" in request.url
            else None,
        )
        page.goto(f"{base_url}/")

        transcript = page.get_by_label("会话记录")
        announcer = page.locator('[aria-live="polite"]')
        expect(announcer).to_have_count(1)
        expect(announcer).to_have_text("")
        expect(
            transcript.get_by_text("Stored replacement tracer", exact=True)
        ).to_be_visible()
        expect(
            transcript.get_by_text(
                "I heard: Stored replacement tracer", exact=True
            )
        ).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()

        due_at = datetime.fromtimestamp(now - 1, timezone.utc).isoformat()
        with Client(base_url=base_url) as client:
            created = client.post(
                "/api/settings/reminders",
                json={"message": "Fixture live event", "due_at": due_at},
            )
        assert created.status_code == 201

        page.get_by_role("link", name="对话", exact=True).click()
        live_message = transcript.get_by_text(
            "Mellowday reminder: Fixture live event", exact=True
        )
        expect(live_message).to_be_visible(timeout=5_000)
        expect(live_message).to_have_count(1)
        expect(announcer).to_have_text("")
        assert len(live_requests) == 1

        page.reload()
        restarted_transcript = page.get_by_label("会话记录")
        persisted_reminder = restarted_transcript.locator(
            ".conversation-event-card",
            has_text="Mellowday reminder: Fixture live event",
        )
        expect(persisted_reminder).to_have_count(1)
        expect(page.locator('[aria-live="polite"]')).to_have_text("")
        browser.close()


def test_replacement_proactive_chat_survives_route_changes_once(
    tmp_path: Path,
) -> None:
    class ProactiveProvider:
        name = "proactive-browser-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            return ProviderReply(
                content='{"send": true, "content": "A gentle local check-in."}'
            )

    now = datetime(2026, 9, 2, 8, tzinfo=timezone.utc).timestamp()
    app = create_app(
        provider=ProactiveProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
        proactive_clock=lambda: now,
        proactive_poll_interval=0.01,
        proactive_minimum_idle_seconds=0,
        proactive_evaluation_interval_seconds=60,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        live_requests: list[str] = []
        page.on(
            "request",
            lambda request: live_requests.append(request.url)
            if "/api/conversations/main/live" in request.url
            else None,
        )
        with page.expect_response(
            lambda response: response.status == 200
            and "/api/conversations/main/live" in response.url
        ):
            page.goto(f"{base_url}/#/today")

        with Client(base_url=base_url) as client:
            saved = client.put(
                "/api/settings/proactive-chat",
                json={
                    "enabled": True,
                    "quiet_hours_start": "00:00",
                    "quiet_hours_end": "00:00",
                    "cooldown_seconds": 0,
                    "daily_limit": 1,
                    "proactive_chat_style": "gentle and brief",
                },
            )
        assert saved.status_code == 200

        announcer = page.get_by_role("status")
        expect(announcer).to_have_text(
            "主动聊天：A gentle local check-in.", timeout=5_000
        )
        page.get_by_role("link", name="对话", exact=True).click()
        proactive_message = page.locator('[data-source="proactive_chat"]').filter(
            has_text="A gentle local check-in."
        )
        expect(proactive_message).to_have_count(1)
        expect(proactive_message).to_be_visible()
        assert len(live_requests) == 1
        browser.close()


def test_replacement_composer_keeps_drafts_and_respects_keyboard_input(
    tmp_path: Path,
) -> None:
    class SlowProvider:
        name = "slow-composer-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            await asyncio.sleep(0.15)
            return ProviderReply(content="A calm reply.")

    app = create_app(
        provider=SlowProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        with Client(base_url=base_url) as client:
            main = client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Main fixture"},
            )
            second = client.post(
                "/api/chat",
                json={
                    "conversation_id": "project-notes",
                    "content": "Project fixture",
                },
            )
        assert main.status_code == 200
        assert second.status_code == 200

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 881, "height": 780})
        page.set_default_timeout(5_000)
        chat_requests: list[dict[str, object]] = []
        page.on(
            "request",
            lambda request: chat_requests.append(
                {
                    "method": request.method,
                    "payload": request.post_data_json,
                }
            )
            if request.url.endswith("/api/chat")
            else None,
        )
        page.goto(f"{base_url}/#/conversation")

        composer = page.get_by_role("textbox", name="消息")
        recent = page.get_by_role("region", name="最近对话")
        recent_buttons = recent.locator(".recent-conversation-select")
        expect(recent_buttons).to_have_count(2)
        composer.fill("主会话草稿")
        recent_buttons.first.click()
        expect(composer).to_have_value("")
        composer.fill("项目会话草稿")
        recent_buttons.nth(1).click()
        expect(composer).to_have_value("主会话草稿")

        composer.dispatch_event("compositionstart")
        composer.press("Enter")
        page.wait_for_timeout(50)
        assert chat_requests == []
        composer.dispatch_event("compositionend")
        composer.fill("主会话草稿")

        composer.press("End")
        composer.press("Shift+Enter")
        expect(composer).to_have_value("主会话草稿\n")
        page.set_viewport_size({"width": 520, "height": 640})
        single_line_height = composer.bounding_box()["height"]
        composer.fill("\n".join(f"第 {index} 行" for index in range(1, 11)))
        grown_height = composer.bounding_box()["height"]
        assert grown_height > single_line_height
        assert grown_height < 240
        expect(page.get_by_role("button", name="发送消息")).to_be_visible()

        composer.fill("通过 Enter 发送")
        composer.press("Enter")
        expect(page.get_by_text("正在发送消息", exact=True)).to_be_visible()
        expect(page.get_by_text("A calm reply.", exact=True).last).to_be_visible()
        expect(page.get_by_text("消息已发送", exact=True)).to_be_visible()
        expect(composer).to_have_value("")
        expect(composer).to_be_focused()
        expect(page.locator('[aria-live="polite"]')).to_have_text(
            "Mellowday：A calm reply."
        )
        assert chat_requests[-1] == {
            "method": "POST",
            "payload": {"conversation_id": "main", "content": "通过 Enter 发送"},
        }

        page.route(
            "**/api/chat",
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body="{}",
            ),
        )
        composer.fill("失败后保留")
        composer.press("Enter")
        expect(page.get_by_text("发送失败", exact=True)).to_be_visible()
        expect(composer).to_have_value("失败后保留")
        expect(composer).to_be_focused()
        browser.close()


def test_replacement_conversation_completes_two_step_confirmation(
    tmp_path: Path,
) -> None:
    executions: list[dict[str, object]] = []

    class ConfirmationProvider:
        name = "conversation-confirmation-script"

        def __init__(self) -> None:
            self.replies = iter(
                (
                    ProviderReply(
                        content="This erases the note permanently. Continue?",
                        tool_calls=(
                            ToolCall(
                                "call-cancel",
                                "erase_note",
                                {"note_id": "note-1"},
                            ),
                        ),
                    ),
                    ProviderReply(content="I left the note unchanged."),
                    ProviderReply(
                        content="This erases the note permanently. Continue?",
                        tool_calls=(
                            ToolCall(
                                "call-accept",
                                "erase_note",
                                {"note_id": "note-1"},
                            ),
                        ),
                    ),
                    ProviderReply(content="The note is gone."),
                    ProviderReply(
                        content="This erases the note permanently. Continue?",
                        tool_calls=(
                            ToolCall(
                                "call-fail",
                                "erase_note",
                                {"note_id": "note-fail"},
                            ),
                        ),
                    ),
                    ProviderReply(content="The note could not be erased."),
                )
            )

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            return next(self.replies)

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        if arguments["note_id"] == "note-fail":
            raise RuntimeError("fixture failure")
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    app = create_app(
        provider=ConfirmationProvider(),
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={
                    "type": "object",
                    "properties": {"note_id": {"type": "string"}},
                    "required": ["note_id"],
                },
                executor=erase_note,
                side_effect="irreversible",
                risk="high",
            ),
        ),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        decisions: list[dict[str, object]] = []
        page.on(
            "request",
            lambda request: decisions.append(request.post_data_json)
            if "/api/settings/confirmations/" in request.url
            and request.url.endswith("/decision")
            else None,
        )
        page.goto(f"{base_url}/#/conversation")
        composer = page.get_by_role("textbox", name="消息")

        composer.fill("Erase note one.")
        composer.press("Enter")
        confirmation = page.get_by_role("group", name="操作确认").last
        expect(confirmation.get_by_text("等待你的确认", exact=True)).to_be_visible()
        page.reload()
        composer = page.get_by_role("textbox", name="消息")
        confirmation = page.get_by_role("group", name="操作确认").last
        expect(confirmation).to_be_visible()
        confirmation.get_by_role("button", name="取消操作").click()
        expect(confirmation.get_by_text("已取消操作", exact=True)).to_be_visible()
        expect(confirmation).to_have_attribute("data-state", "cancelled")
        expect(confirmation).to_be_focused()
        expect(page.get_by_text("I left the note unchanged.", exact=True)).to_be_visible()
        assert executions == []

        composer.fill("Erase note one now.")
        composer.press("Enter")
        confirmation = page.get_by_role("group", name="操作确认").last
        confirmation.get_by_role("button", name="确认执行").click()
        expect(confirmation.get_by_text("操作已完成", exact=True)).to_be_visible()
        expect(confirmation).to_have_attribute("data-state", "success")
        expect(confirmation).to_be_focused()
        expect(page.get_by_text("The note is gone.", exact=True)).to_be_visible()
        assert executions == [{"note_id": "note-1"}]

        composer.fill("Erase the failing note.")
        composer.press("Enter")
        confirmation = page.get_by_role("group", name="操作确认").last
        confirmation.get_by_role("button", name="确认执行").click()
        expect(confirmation.get_by_text("操作执行失败", exact=True)).to_be_visible()
        expect(confirmation).to_have_attribute("data-state", "failure")
        expect(confirmation).to_be_focused()
        expect(confirmation.get_by_role("button")).to_have_count(0)
        expect(page.get_by_text("The note could not be erased.", exact=True)).to_be_visible()
        assert [decision["decision"] for decision in decisions] == [
            "reject",
            "accept",
            "accept",
        ]
        browser.close()


def test_replacement_life_tasks_supports_the_complete_task_lifecycle(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url:
        with Client(base_url=base_url) as client:
            client.post(
                "/api/settings/tasks",
                json={"title": "Read spec", "details": "Issue 38"},
            )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 520, "height": 640})
            page.goto(f"{base_url}/#/life")

            expect(page).to_have_url(f"{base_url}/#/life/tasks")
            expect(page.get_by_role("navigation", name="生活二级导航")).to_be_visible()
            expect(page.get_by_text("Read spec", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            title = page.get_by_label("任务标题", exact=True)
            title.fill("Submit report")
            page.get_by_label("任务详情", exact=True).fill("Attach charts")
            page.get_by_label("截止日期", exact=True).fill("2026-09-04")
            page.get_by_role("button", name="添加任务", exact=True).click()

            task_status = page.get_by_role("status", name="任务状态")
            expect(task_status).to_contain_text("任务已添加")
            expect(page.get_by_text("Submit report", exact=True)).to_be_visible()
            expect(page.get_by_text("Attach charts", exact=True)).to_be_visible()

            page.get_by_role("button", name="完成 Submit report").click()
            expect(page.get_by_role("button", name="重新打开 Submit report")).to_be_visible()
            page.get_by_role("button", name="编辑 Submit report").click()
            expect(title).to_be_focused()
            title.fill("Send report")
            page.get_by_role("button", name="保存任务", exact=True).click()
            expect(page.get_by_text("Send report", exact=True)).to_be_visible()

            delete_button = page.get_by_role("button", name="删除 Send report")
            delete_button.click()
            confirmation = page.get_by_role("dialog", name="删除任务")
            expect(confirmation).to_contain_text("Send report")
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
            expect(task_status).to_contain_text("已取消删除任务")

            delete_button.click()
            page.get_by_role("button", name="确认删除", exact=True).click()
            expect(task_status).to_contain_text("任务已删除")
            expect(page.get_by_text("Send report", exact=True)).not_to_be_visible()
            browser.close()


def test_replacement_life_tasks_covers_inactive_load_and_visible_states(
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

        def delay_task_list(route, request) -> None:
            if request.method == "GET":
                delayed_routes.append(route)
            else:
                route.continue_()

        page.route("**/api/settings/tasks", delay_task_list)
        page.goto(f"{base_url}/#/life/tasks")
        expect(page.get_by_text("正在加载任务…", exact=True)).to_be_visible()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_routes
        delayed_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body='{"tasks":[{"id":"late","title":"Late task","details":null,'
            '"completed":false,"deadline":null,"created_at":1,'
            '"updated_at":1,"completed_at":null}]}',
        )
        expect(page.get_by_text("Late task", exact=True)).not_to_be_visible()

        page.unroute("**/api/settings/tasks", delay_task_list)
        page.route(
            "**/api/settings/tasks",
            lambda route, request: route.fulfill(status=503, body="Unavailable")
            if request.method == "GET"
            else route.continue_(),
        )
        page.goto(f"{base_url}/#/life/tasks")
        expect(page.get_by_role("alert")).to_contain_text("任务加载失败")

        page.unroute("**/api/settings/tasks")
        page.get_by_role("button", name="重试", exact=True).click()
        expect(page.get_by_text("还没有任务。", exact=True)).to_be_visible()

        page.get_by_role("button", name="添加任务", exact=True).click()
        expect(page.get_by_role("status", name="任务状态")).to_contain_text(
            "请输入任务标题"
        )
        expect(page.get_by_label("任务标题", exact=True)).to_be_focused()

        page.emulate_media(reduced_motion="reduce")
        transition_duration = page.locator(".task-editor").evaluate(
            "node => getComputedStyle(node).transitionDuration"
        )
        assert transition_duration in {"0.01ms", "1e-05s"}

        delayed_mutations = []
        unexpected_task_loads = []

        def delay_task_create(route, request) -> None:
            if request.method == "POST":
                delayed_mutations.append(route)
            elif request.method == "GET":
                unexpected_task_loads.append(request)
                route.continue_()
            else:
                route.continue_()

        page.route("**/api/settings/tasks", delay_task_create)
        page.get_by_label("任务标题", exact=True).fill("Delayed task")
        page.get_by_role("button", name="添加任务", exact=True).click()
        page.get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_role("heading", name="今天", exact=True)).to_be_visible()
        assert delayed_mutations
        delayed_mutations[0].fulfill(
            status=201,
            content_type="application/json",
            body='{"task":{"id":"delayed","title":"Delayed task",'
            '"details":null,"completed":false,"deadline":null,'
            '"created_at":1,"updated_at":1,"completed_at":null}}',
        )
        page.wait_for_timeout(100)
        assert unexpected_task_loads == []
        page.unroute("**/api/settings/tasks", delay_task_create)

        with Client(base_url=base_url) as client:
            client.post("/api/settings/tasks", json={"title": "Delete failure"})
        page.goto(f"{base_url}/#/life/tasks")
        delete_button = page.get_by_role("button", name="删除 Delete failure")

        def fail_delete_decision(route, request) -> None:
            if request.method == "DELETE":
                route.fulfill(status=503, body="Unavailable")
            else:
                route.continue_()

        page.route("**/api/settings/tasks/**", fail_delete_decision)
        delete_button.click()
        confirmation = page.get_by_role("dialog", name="删除任务")
        confirmation.get_by_role("button", name="确认删除", exact=True).click()
        expect(confirmation.get_by_role("status", name="删除状态")).to_contain_text(
            "任务删除失败"
        )
        browser.close()
