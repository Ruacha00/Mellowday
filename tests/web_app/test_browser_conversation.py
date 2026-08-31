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
