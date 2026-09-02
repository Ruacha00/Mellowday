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
    Skill,
    Tool,
    ToolCall,
    ToolOutcome,
    UndoMetadata,
)
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
        page.goto(f"{base_url}/replacement")

        expect(
            page.get_by_role("heading", name="我在这里，陪你梳理今天。")
        ).to_be_visible()
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
        page.goto(f"{base_url}/replacement#/settings")

        expect(page).to_have_url(f"{base_url}/replacement#/settings/appearance")
        expect(page.get_by_role("heading", name="外观")).to_be_visible()
        expect(page.get_by_role("link", name="设置", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(
            page.get_by_role("link", name="人格设定", exact=True)
        ).to_be_visible()

        page.get_by_role("link", name="生活", exact=True).click()
        expect(page).to_have_url(f"{base_url}/replacement#/life/tasks")
        expect(page.get_by_role("heading", name="任务")).to_be_visible()

        page.get_by_role("link", name="记忆", exact=True).click()
        expect(page).to_have_url(f"{base_url}/replacement#/memory")
        expect(page.get_by_role("heading", name="记忆管理")).to_be_visible()

        page.go_back()
        expect(page).to_have_url(f"{base_url}/replacement#/life/tasks")
        page.go_forward()
        expect(page).to_have_url(f"{base_url}/replacement#/memory")

        page.goto(f"{base_url}/replacement#/unknown")
        expect(page).to_have_url(f"{base_url}/replacement#/conversation")
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
        page.goto(f"{base_url}/replacement")

        expect(page.locator("html")).to_have_attribute("data-theme", "sky")
        trigger = page.get_by_role("button", name="外观，当前主题：晴空")
        trigger.click()
        popover = page.get_by_role("dialog", name="外观")
        expect(popover).to_have_attribute("aria-modal", "false")
        expect(popover).to_be_visible()

        popover.get_by_role("radio", name="简约").click()
        popover.get_by_role("slider", name="强调色色相").fill("286")
        popover.get_by_role("slider", name="背景亮度").fill("91")
        expect(page.locator("html")).to_have_attribute("data-theme", "minimal")
        expect(page.locator("[data-theme-decoration]")).to_have_count(0)

        page.keyboard.press("Escape")
        expect(popover).not_to_be_visible()
        expect(
            page.get_by_role("button", name="外观，当前主题：简约")
        ).to_be_focused()
        page.get_by_role("link", name="设置", exact=True).click()
        appearance_page = page.get_by_label("外观设置")
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
        page.goto(f"{base_url}/replacement")

        trigger = page.get_by_role("button", name="外观，当前主题：晴空")
        trigger.focus()
        page.keyboard.press("Enter")
        popover = page.get_by_role("dialog", name="外观")
        box = popover.bounding_box()
        assert box is not None
        assert box["width"] >= 480
        assert box["x"] >= 17
        assert box["x"] + box["width"] <= 503

        sky = popover.get_by_role("radio", name="晴空")
        sakura = popover.get_by_role("radio", name="樱粉")
        minimal = popover.get_by_role("radio", name="简约")
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

        page.keyboard.press("Escape")
        expect(popover).not_to_be_visible()
        expect(trigger).to_be_focused()

        trigger.click()
        page.mouse.click(4, 300)
        expect(popover).not_to_be_visible()
        expect(trigger).to_be_focused()

        trigger.focus()
        page.keyboard.press("Enter")
        popover.get_by_role("radio", name="夜色").focus()
        page.keyboard.press("Enter")
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
            page.goto(f"{base_url}/replacement")
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
        page.goto(f"{base_url}/replacement")
        workspace = page.locator(".conversation-workspace")
        baseline_box = workspace.bounding_box()
        baseline_type = page.locator(".message p").first.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return [style.fontFamily, style.fontSize, style.lineHeight];
            }"""
        )
        assert baseline_box is not None

        page.get_by_role("button", name="外观，当前主题：晴空").click()
        popover = page.get_by_role("dialog", name="外观")
        for theme, label in (
            ("sky", "晴空"),
            ("sakura", "樱粉"),
            ("mint", "薄荷"),
            ("night", "夜色"),
            ("minimal", "简约"),
        ):
            popover.get_by_role("radio", name=label).click()
            expect(page.locator("html")).to_have_attribute("data-theme", theme)
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
            control_contrasts = page.locator(
                ".appearance-trigger, .theme-option[aria-checked='false']"
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
        page.goto(f"{base_url}/replacement")

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
        browser_page.goto(f"{base_url}/replacement")
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
        desktop_page.goto(f"{base_url}/replacement")
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
        page.goto(f"{base_url}/replacement")
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
        page.goto(f"{base_url}/replacement")

        for width, height in ((1200, 780), (520, 640)):
            page.set_viewport_size({"width": width, "height": height})
            composer = page.get_by_label("消息编辑器占位").bounding_box()
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
        page.goto(f"{base_url}/replacement")
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
        page.goto(f"{base_url}/replacement#/today")
        recent = page.locator(".recent-rail .recent-list button")
        expect(recent.first).to_contain_text("Second conversation fixture")
        assert all(
            "project-internal-id" not in item for item in recent.all_inner_texts()
        )
        recent.first.click()

        expect(page).to_have_url(f"{base_url}/replacement#/conversation")
        expect(
            page.get_by_label("会话记录").get_by_text(
                "Second conversation fixture", exact=True
            )
        ).to_be_visible()
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
        page.goto(f"{base_url}/replacement")

        transcript = page.get_by_label("会话记录")
        expect(
            transcript.get_by_text("Stored replacement tracer", exact=True)
        ).to_be_visible()
        expect(
            transcript.get_by_text(
                "I heard: Stored replacement tracer", exact=True
            )
        ).to_be_visible()

        due_at = datetime.fromtimestamp(now - 1, timezone.utc).isoformat()
        with Client(base_url=base_url) as client:
            created = client.post(
                "/api/settings/reminders",
                json={"message": "Fixture live event", "due_at": due_at},
            )
        assert created.status_code == 201

        live_message = transcript.get_by_text(
            "Mellowday reminder: Fixture live event", exact=True
        )
        expect(live_message).to_be_visible(timeout=5_000)
        expect(live_message).to_have_count(1)
        assert len(live_requests) == 1

        page.reload()
        restarted_transcript = page.get_by_label("会话记录")
        expect(
            restarted_transcript.get_by_text(
                "Mellowday reminder: Fixture live event", exact=True
            )
        ).to_have_count(1)
        browser.close()


def test_user_can_chat_from_the_conversation_surface(tmp_path: Path) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)

        expect(page.get_by_role("heading", name="Mellowday")).to_be_visible()
        page.get_by_label("Message").fill("Hello from Mellowday")
        page.get_by_role("button", name="Send").click()

        expect(page.locator('[data-role="user"] p').last).to_have_text(
            "Hello from Mellowday"
        )
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I heard: Hello from Mellowday"
        )
        browser.close()


def test_user_can_inspect_and_manage_capabilities_from_settings(
    tmp_path: Path,
) -> None:
    loads: list[str] = []

    async def read_status(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        return {"conversation_id": conversation_id, **arguments}

    app = create_app(
        provider=FakeProvider(),
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
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="Settings").click()

        expect(page.get_by_role("heading", name="Settings", exact=True)).to_be_visible()
        expect(page.get_by_text("status_read", exact=True)).to_be_visible()
        expect(page.get_by_text("status:read", exact=True)).to_be_visible()
        expect(page.get_by_text("plain_language", exact=True)).to_be_visible()
        enablement = page.get_by_role(
            "checkbox", name="Enable plain_language Skill"
        )
        expect(enablement).to_be_checked()
        enablement.uncheck()
        expect(page.get_by_text("Disabled", exact=True)).to_be_visible()
        assert loads == []
        browser.close()


def test_due_reminder_is_delivered_live_once_and_survives_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    now = 1_788_200_100.0
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=database_path,
        audit_path=None,
        reminder_clock=lambda: now,
        reminder_poll_interval=0.05,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        due_at = datetime.fromtimestamp(now - 1, timezone.utc).isoformat()
        with Client(base_url=base_url) as client:
            created = client.post(
                "/api/settings/reminders",
                json={"message": "Join the call", "due_at": due_at},
            )
        assert created.status_code == 201
        expect(
            page.get_by_text("Mellowday reminder: Join the call", exact=True)
        ).to_be_visible(timeout=5_000)
        browser.close()

    restarted = create_app(
        provider=FakeProvider(),
        conversation_database_path=database_path,
        audit_path=None,
        reminder_clock=lambda: now,
        reminder_poll_interval=0.05,
    )
    with running_server(restarted) as base_url:
        with Client(base_url=base_url) as client:
            reminder = client.get("/api/settings/reminders").json()["reminders"][0]
            conversation = client.get("/api/conversations/main").json()

    assert reminder["delivery_state"] == "delivered"
    assert reminder["delivery_attempted_at"] is not None
    assert [
        message["content"]
        for message in conversation["messages"]
        if message["content"] == "Mellowday reminder: Join the call"
    ] == ["Mellowday reminder: Join the call"]


def test_conversation_surface_creates_a_task_through_the_registered_tool(
    tmp_path: Path,
) -> None:
    class TaskProvider:
        name = "task-surface-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                return ProviderReply(content="I added the report Task.")
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "create-report",
                        "task_create",
                        {"title": "Submit report", "deadline": "2026-09-04"},
                    ),
                )
            )

    app = create_app(
        provider=TaskProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.get_by_label("Message").fill("Add a Task to submit the report Friday.")
        page.get_by_role("button", name="Send").click()

        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I added the report Task."
        )
        page.get_by_role("button", name="Settings").click()
        expect(page.get_by_text("Submit report", exact=True)).to_be_visible()
        expect(page.get_by_text("Deadline 2026-09-04", exact=True)).to_be_visible()
        browser.close()


def test_user_can_view_and_edit_the_single_persona_from_settings(
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
        page.goto(base_url)
        page.get_by_role("button", name="Settings").click()

        values = {
            "Name": "Luma",
            "Identity": "an evening companion",
            "Character": "warm and candid",
            "Speaking style": "brief with gentle humor",
            "Relationship framing": "a trusted companion",
            "Conversational boundaries": "stay truthful",
            "Proactive-chat style": "low-pressure check-ins",
        }
        for label, value in values.items():
            field = page.get_by_label(label, exact=True)
            expect(field).to_be_visible()
            field.fill(value)

        page.get_by_role("button", name="Save Persona").click()
        expect(page.locator("#settings-panel").get_by_role("status")).to_contain_text(
            "Persona saved."
        )
        page.get_by_role("button", name="Back to conversation").click()
        page.get_by_role("button", name="Settings").click()

        for label, value in values.items():
            expect(page.get_by_label(label, exact=True)).to_have_value(value)
        browser.close()


def test_user_can_manage_tasks_from_settings(tmp_path: Path) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(base_url)
        page.get_by_role("button", name="Settings").click()

        page.get_by_label("Task title", exact=True).fill("Submit report")
        page.get_by_label("Task details", exact=True).fill("Attach charts")
        page.get_by_label("Task deadline", exact=True).fill("2026-09-04")
        page.get_by_role("button", name="Add Task").click()

        expect(page.locator("#settings-status")).to_have_text("Task added.")
        expect(page.get_by_text("Submit report", exact=True)).to_be_visible()
        expect(page.get_by_text("Attach charts", exact=True)).to_be_visible()
        page.get_by_role("button", name="Complete Submit report").click()
        expect(page.get_by_role("button", name="Reopen Submit report")).to_be_visible()
        page.get_by_role("button", name="Reopen Submit report").click()
        page.get_by_role("button", name="Edit Submit report").click()
        page.get_by_label("Task title", exact=True).fill("Send report")
        page.get_by_role("button", name="Save Task").click()
        expect(page.get_by_text("Send report", exact=True)).to_be_visible()
        page.get_by_role("button", name="Delete Send report").click()
        expect(page.get_by_text("No Tasks yet.", exact=True)).to_be_visible()
        browser.close()


def test_user_can_manage_and_search_notes_from_settings(tmp_path: Path) -> None:
    class NoteProvider:
        name = "note-surface-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                return ProviderReply(content="I saved your Trip ideas Note.")
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "save-trip-note",
                        "note_create",
                        {"title": "Trip ideas", "content": "Visit Kyoto"},
                    ),
                )
            )

    app = create_app(
        provider=NoteProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(base_url)
        page.get_by_label("Message").fill("Save a Note about visiting Kyoto.")
        page.get_by_role("button", name="Send").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I saved your Trip ideas Note."
        )
        page.get_by_role("button", name="Settings").click()

        expect(page.get_by_text("Trip ideas", exact=True)).to_be_visible()
        expect(page.get_by_text("Visit Kyoto", exact=True)).to_be_visible()
        page.get_by_label("Note title", exact=True).fill("Packing list")
        page.get_by_label("Note content", exact=True).fill("Passport")
        page.get_by_role("button", name="Add Note").click()

        expect(page.locator("#settings-status")).to_have_text("Note added.")
        expect(page.get_by_text("Packing list", exact=True)).to_be_visible()
        page.get_by_label("Search Notes", exact=True).fill("missing")
        expect(page.get_by_text("No matching Notes.", exact=True)).to_be_visible()
        page.get_by_label("Search Notes", exact=True).fill("kyoto")
        expect(page.get_by_text("Trip ideas", exact=True)).to_be_visible()
        page.get_by_role("button", name="Edit Trip ideas").click()
        page.get_by_label("Note content", exact=True).fill("Visit Kyoto and Nara")
        page.get_by_role("button", name="Save Note").click()
        expect(page.get_by_text("Visit Kyoto and Nara", exact=True)).to_be_visible()
        page.get_by_role("button", name="Delete Trip ideas").click()
        expect(page.get_by_text("No matching Notes.", exact=True)).to_be_visible()
        browser.close()


def test_user_can_open_and_refresh_the_daily_review_from_settings(
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
                json={"title": "Submit report", "deadline": "2026-09-01"},
            )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url)
            page.get_by_role("button", name="Settings").click()

            review = page.locator("#daily-review")
            expect(
                review.get_by_role("heading", name="Daily Review")
            ).to_be_visible()
            expect(review.locator("#daily-review-metadata")).to_contain_text(
                "2026-09-01 · Asia/Shanghai"
            )
            expect(
                review.get_by_text("Task · Submit report", exact=True)
            ).to_be_visible()
            expect(review.get_by_text("Due today", exact=True)).to_be_visible()
            expect(review.get_by_text("No Reminders", exact=True)).to_be_visible()

            with Client(base_url=base_url) as client:
                client.post(
                    "/api/settings/tasks",
                    json={"title": "Renew passport", "deadline": "2026-08-30"},
                )
            page.get_by_role("button", name="Refresh review").click()
            expect(
                review.get_by_text("Task · Renew passport", exact=True)
            ).to_be_visible()
            expect(review.get_by_text("Overdue", exact=True)).to_be_visible()
            browser.close()


def test_user_can_search_correct_and_forget_memory_from_settings(
    tmp_path: Path,
) -> None:
    class MemoryProvider:
        name = "memory-browser-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                return ProviderReply(content="I'll remember that.")
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "remember-browser",
                        "memory_remember",
                        {
                            "content": "I prefer concise replies.",
                            "kind": "preference",
                            "evidence": "Remember that I prefer concise replies.",
                        },
                    ),
                )
            )

    app = create_app(
        provider=MemoryProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.get_by_label("Message").fill(
            "Remember that I prefer concise replies."
        )
        page.get_by_role("button", name="Send").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I'll remember that."
        )

        page.get_by_role("button", name="Settings").click()
        expect(page.get_by_role("heading", name="Memory", exact=True)).to_be_visible()
        page.get_by_label("Search Memory").fill("concise")
        expect(page.locator("#memory-list")).to_contain_text(
            "I prefer concise replies."
        )
        page.get_by_role("button", name="Edit I prefer concise replies.").click()
        page.get_by_label("Memory content").fill("I prefer detailed replies.")
        page.get_by_role("button", name="Save Memory").click()
        expect(page.locator("#settings-status")).to_have_text("Memory saved.")
        expect(page.locator("#memory-list")).to_contain_text(
            "I prefer detailed replies."
        )

        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete I prefer detailed replies.").click()
        expect(page.locator("#settings-status")).to_have_text("Memory deleted.")
        expect(page.locator("#memory-list")).to_contain_text("No Memory yet.")
        browser.close()


def test_user_can_manage_reminders_from_settings(tmp_path: Path) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.get_by_role("button", name="Settings").click()

        page.get_by_label("Reminder text", exact=True).fill("Join the call")
        page.get_by_label("Reminder due time", exact=True).fill(
            "2026-09-04T17:00"
        )
        page.get_by_role("button", name="Add Reminder").click()

        expect(page.locator("#settings-status")).to_have_text("Reminder added.")
        expect(page.get_by_text("Join the call", exact=True)).to_be_visible()
        page.get_by_role("button", name="Edit Join the call").click()
        page.get_by_label("Reminder text", exact=True).fill("Join stand-up")
        page.get_by_role("button", name="Save Reminder").click()
        expect(page.get_by_text("Join stand-up", exact=True)).to_be_visible()
        page.get_by_role("button", name="Dismiss Join stand-up").click()
        expect(page.get_by_text("Dismissed", exact=True)).to_be_visible()
        page.get_by_role("button", name="Cancel Join stand-up").click()
        expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete Join stand-up").click()
        expect(page.get_by_text("No Reminders yet.", exact=True)).to_be_visible()
        browser.close()


def test_user_can_manage_calendar_events_and_see_conflicts_from_settings(
    tmp_path: Path,
) -> None:
    app = create_app(
        provider=FakeProvider(),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        installation_timezone="Asia/Shanghai",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(base_url)
        page.get_by_role("button", name="Settings").click()

        page.get_by_label("Calendar Event title", exact=True).fill("Project review")
        page.get_by_label("Calendar Event start time", exact=True).fill(
            "2026-09-04T17:00"
        )
        page.get_by_label("Calendar Event end time", exact=True).fill(
            "2026-09-04T18:00"
        )
        page.get_by_label("Calendar Event details", exact=True).fill(
            "Discuss launch"
        )
        page.get_by_role("button", name="Add Calendar Event").click()
        expect(page.locator("#settings-status")).to_have_text(
            "Calendar Event added."
        )

        page.get_by_label("Calendar Event title", exact=True).fill("Call")
        page.get_by_label("Calendar Event start time", exact=True).fill(
            "2026-09-04T17:30"
        )
        page.get_by_label("Calendar Event end time", exact=True).fill(
            "2026-09-04T18:30"
        )
        page.get_by_role("button", name="Add Calendar Event").click()

        expect(page.get_by_text("Conflicts with Project review.", exact=True)).to_be_visible()
        page.get_by_role("button", name="Edit Call").click()
        page.get_by_label("Calendar Event start time", exact=True).fill(
            "2026-09-04T19:00"
        )
        page.get_by_label("Calendar Event end time", exact=True).fill("")
        page.get_by_role("button", name="Save Calendar Event").click()
        expect(page.get_by_text("No conflicts.", exact=True).last).to_be_visible()
        page.get_by_role("button", name="Delete Call").click()
        expect(page.get_by_text("Call", exact=True)).not_to_be_visible()
        browser.close()


def test_user_can_manage_model_providers_from_settings(tmp_path: Path) -> None:
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
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
        provider_transport=ValidTransport(),
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.get_by_role("button", name="Settings").click()

        page.get_by_label("Provider name", exact=True).fill("Local model")
        page.get_by_label("Base URL", exact=True).fill("http://localhost:9000/v1")
        page.get_by_label("Model", exact=True).fill("first-model")
        page.get_by_label("API key", exact=True).fill("local-secret")
        page.get_by_role("button", name="Add Provider").click()

        expect(page.get_by_text("••••cret", exact=True)).to_be_visible()
        page.get_by_role("button", name="Select Local model").click()
        expect(page.get_by_text("Selected", exact=True)).to_be_visible()
        page.get_by_role("button", name="Validate Local model").click()
        expect(page.locator("#settings-status")).to_have_text(
            "Local model validated."
        )

        page.get_by_role("button", name="Edit Local model").click()
        page.get_by_label("Model", exact=True).fill("edited-model")
        page.get_by_role("button", name="Save Provider").click()
        expect(page.get_by_text("edited-model", exact=True)).to_be_visible()

        enablement = page.get_by_role(
            "checkbox", name="Enable Local model Provider"
        )
        enablement.uncheck()
        expect(page.get_by_text("Disabled", exact=True)).to_be_visible()
        browser.close()


def test_conversation_history_survives_a_real_backend_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"

    with running_server(
        create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
    ) as base_url:
        with Client(base_url=base_url) as client:
            response = client.post(
                "/api/chat",
                json={"conversation_id": "restart", "content": "Persist me"},
            )
        assert response.status_code == 200

    with running_server(
        create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
    ) as base_url:
        with Client(base_url=base_url) as client:
            persisted = client.get("/api/conversations/restart")

    assert persisted.status_code == 200
    assert persisted.json()["messages"] == [
        {"role": "user", "content": "Persist me"},
        {"role": "assistant", "content": "I heard: Persist me"},
    ]


def test_settings_reviews_and_resets_conversation_history(tmp_path: Path) -> None:
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
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.get_by_label("Message").fill("A message to review")
        page.get_by_role("button", name="Send").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I heard: A message to review"
        )

        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator('[data-role="user"] p').last).to_have_text(
            "A message to review"
        )

        page.get_by_role("button", name="Settings").click()
        expect(
            page.get_by_role("heading", name="Conversation History")
        ).to_be_visible()
        page.get_by_role("button", name="main · 2 messages").click()
        history_settings = page.get_by_label("Conversation History")
        expect(history_settings.locator("#history-metadata")).to_contain_text(
            "2 messages · 47 characters"
        )
        expect(
            history_settings.get_by_text("A message to review", exact=True)
        ).to_be_visible()
        expect(
            history_settings.get_by_text(
                "I heard: A message to review", exact=True
            )
        ).to_be_visible()

        page.get_by_role("button", name="Reset conversation").click()
        expect(
            page.get_by_text(
                "This permanently deletes this conversation's messages.",
                exact=True,
            )
        ).to_be_visible()
        expect(page.get_by_text("No conversations yet.")).not_to_be_visible()
        page.get_by_role("button", name="Confirm reset").click()
        expect(page.get_by_text("No conversations yet.")).to_be_visible()
        page.get_by_role("button", name="Back to conversation").click()
        expect(page.locator('[data-role="user"]')).to_have_count(0)
        assert console_errors == []
        browser.close()


def test_user_can_reject_pending_confirmation_from_settings(
    tmp_path: Path,
) -> None:
    executions: list[dict[str, object]] = []

    class ConfirmationProvider:
        name = "confirmation-script"

        def __init__(self) -> None:
            self.replies = iter(
                (
                    ProviderReply(
                        content="This erases the note permanently. Continue?",
                        tool_calls=(
                            ToolCall(
                                "call-delete",
                                "erase_note",
                                {"note_id": "note-1"},
                            ),
                        ),
                    ),
                    ProviderReply(content="Okay, I left the note where it was."),
                )
            )

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            return next(self.replies)

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
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
        page.goto(base_url)
        page.get_by_label("Message").fill("Erase note one.")
        page.get_by_role("button", name="Send").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "This erases the note permanently. Continue?"
        )

        page.get_by_role("button", name="Settings").click()
        expect(page.get_by_role("heading", name="Pending confirmations")).to_be_visible()
        expect(
            page.locator("#confirmation-list").get_by_text(
                "erase_note", exact=True
            )
        ).to_be_visible()
        page.get_by_role("button", name="Reject erase_note confirmation").click()
        expect(page.locator("#settings-status")).to_have_text(
            "Confirmation rejected."
        )
        expect(page.locator("#recent-confirmation-list")).to_contain_text(
            "rejected"
        )

        page.get_by_role("button", name="Back to conversation").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "Okay, I left the note where it was."
        )
        assert executions == []
        browser.close()


def test_user_can_inspect_undo_metadata_in_audit_history(tmp_path: Path) -> None:
    class UndoProvider:
        name = "undo-script"

        def __init__(self) -> None:
            self.replies = iter(
                (
                    ProviderReply(
                        tool_calls=(
                            ToolCall(
                                "call-save",
                                "save_note",
                                {"content": "Buy tea"},
                            ),
                        )
                    ),
                    ProviderReply(content="I saved the note."),
                )
            )

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            return next(self.replies)

    async def save_note(
        arguments: dict[str, object], conversation_id: str
    ) -> ToolOutcome:
        return ToolOutcome(
            value={"note_id": "note-1", "conversation_id": conversation_id},
            undo=UndoMetadata(
                tool="delete_note", arguments={"note_id": "note-1"}
            ),
        )

    app = create_app(
        provider=UndoProvider(),
        tools=(
            Tool(
                name="save_note",
                description="Save one note.",
                input_schema={
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
                executor=save_note,
                side_effect="reversible",
            ),
        ),
        conversation_database_path=tmp_path / "mellowday.sqlite3",
        audit_path=None,
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.get_by_label("Message").fill("Save a tea note.")
        page.get_by_role("button", name="Send").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I saved the note."
        )

        page.get_by_role("button", name="Settings").click()
        undo = page.get_by_text("Undo available", exact=True)
        expect(undo).to_be_visible()
        undo.click()
        expect(page.locator("#audit-list").get_by_text("delete_note")).to_be_visible()
        browser.close()


def test_user_can_operate_and_diagnose_from_integrated_settings(
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
        page.goto(base_url)
        page.get_by_label("Message").fill("ordinary history")
        page.get_by_role("button", name="Send").click()
        expect(page.locator('[data-role="assistant"] p').last).to_have_text(
            "I heard: ordinary history"
        )

        page.get_by_role("button", name="Settings").click()
        expect(page.get_by_role("heading", name="Service status")).to_be_visible()
        expect(page.get_by_text("Healthy", exact=True)).to_be_visible()
        expect(page.get_by_text("fake · Not Checked", exact=True)).to_be_visible()
        expect(page.get_by_text("1 conversation", exact=True)).to_be_visible()

        page.get_by_label("Diagnostic input").fill("probe the core")
        page.get_by_role("button", name="Run diagnostic probe").click()
        expect(page.locator("#diagnostic-result")).to_contain_text(
            "I heard: probe the core"
        )
        expect(page.locator("#conversation-list")).not_to_contain_text(
            "diagnostic-probe"
        )

        page.get_by_label("Event type").select_option("turn_completed")
        page.get_by_role("button", name="Refresh runtime events").click()
        expect(page.locator("#runtime-event-list")).to_contain_text(
            "turn_completed"
        )

        page.get_by_label("Minimum log level").select_option("WARNING")
        page.get_by_label("Log search").fill("marker")
        logging.getLogger("mellowday.browser_test").warning(
            "browser diagnostics marker"
        )
        expect(page.locator("#runtime-log-list")).to_contain_text(
            "browser diagnostics marker"
        )
        page.route("**/api/logs/recent*", lambda route: route.abort())
        page.get_by_role("button", name="Refresh runtime logs").click()
        expect(page.locator("#settings-status")).to_contain_text("unavailable:")
        browser.close()
