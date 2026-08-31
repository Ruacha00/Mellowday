import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

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
