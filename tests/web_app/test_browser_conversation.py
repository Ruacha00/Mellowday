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

        page.get_by_label("Note title", exact=True).fill("Trip ideas")
        page.get_by_label("Note content", exact=True).fill("Visit Kyoto")
        page.get_by_role("button", name="Add Note").click()

        expect(page.locator("#settings-status")).to_have_text("Note added.")
        expect(page.get_by_text("Trip ideas", exact=True)).to_be_visible()
        expect(page.get_by_text("Visit Kyoto", exact=True)).to_be_visible()
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
