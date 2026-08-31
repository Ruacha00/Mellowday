import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI
from playwright.sync_api import expect, sync_playwright

from mellowday.agent_core import FakeProvider, Skill, Tool
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


def test_user_can_chat_from_the_conversation_surface() -> None:
    app = create_app(provider=FakeProvider())

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


def test_user_can_inspect_and_manage_capabilities_from_settings() -> None:
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
    )

    with running_server(app) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="Settings").click()

        expect(page.get_by_role("heading", name="Capabilities")).to_be_visible()
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
