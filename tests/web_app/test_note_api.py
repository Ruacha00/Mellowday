"""Note behavior at the browser-facing API boundary."""

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest, ToolCall
from mellowday.web_app import create_app


class FakeProvider:
    name = "fake"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        return ProviderReply(content=request.messages[-1].content)


def test_settings_manages_searchable_notes_with_consistent_audit(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            invalid = await client.post(
                "/api/settings/notes", json={"content": "   "}
            )
            created = await client.post(
                "/api/settings/notes",
                json={"title": "Trip ideas", "content": "Visit Kyoto"},
            )
            note_id = created.json()["note"]["id"]
            retrieved = await client.get(f"/api/settings/notes/{note_id}")
            searched = await client.get("/api/settings/notes", params={"q": "kyoto"})
            updated = await client.patch(
                f"/api/settings/notes/{note_id}",
                json={"title": None, "content": "Visit Kyoto and Nara"},
            )
            audit = await client.get("/api/settings/audit")
            capabilities = await client.get("/api/settings/capabilities")

        restarted = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            persisted = await client.get(f"/api/settings/notes/{note_id}")
            confirmation_response = await client.post(
                f"/api/settings/notes/{note_id}/delete-confirmation"
            )
            confirmation = confirmation_response.json()["confirmation"]
            deleted = await client.request(
                "DELETE",
                f"/api/settings/notes/{note_id}",
                json={
                    "confirmation_id": confirmation["id"],
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )

        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "invalid_note"
        assert created.status_code == 201
        assert retrieved.json() == created.json()
        assert searched.json()["notes"] == [created.json()["note"]]
        assert updated.json()["note"]["title"] is None
        assert persisted.json() == updated.json()
        changes = [
            event
            for event in audit.json()["events"]
            if event["type"] == "application_action_completed"
        ]
        assert [event["details"]["action"] for event in changes] == [
            "created",
            "updated",
        ]
        assert all(event["details"]["resource_type"] == "note" for event in changes)
        assert {tool["name"] for tool in capabilities.json()["tools"]} >= {
            "note_create",
            "note_get",
            "note_search",
            "note_update",
            "note_delete",
        }
        assert confirmation["binding"]["tool"] == "note_delete"
        assert deleted.json()["deleted_note"]["id"] == note_id

    asyncio.run(exercise())


def test_chat_runs_the_complete_note_tool_lifecycle_and_clarifies_ambiguity(
    tmp_path: Path,
) -> None:
    class NoteProvider:
        name = "note-script"

        def __init__(self) -> None:
            self.note_id = ""
            self.results: list[str] = []

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                result = request.tool_results[-1]
                if result.error == "ambiguous_intent":
                    return ProviderReply(content="What would you like me to save?")
                self.results.append(result.name)
                if result.name == "note_create":
                    self.note_id = result.result["note"]["id"]
                return ProviderReply(content=f"Finished {result.name}.")
            command = request.messages[-1].content
            calls = {
                "ambiguous": ToolCall(
                    "ambiguous",
                    "note_create",
                    {"title": "Door code", "content": "The code is 2468."},
                    intent_clarity="ambiguous",
                ),
                "create": ToolCall(
                    "create",
                    "note_create",
                    {"title": "Door code", "content": "The code is 2468."},
                ),
                "retrieve": ToolCall(
                    "retrieve", "note_get", {"note_id": self.note_id}
                ),
                "update": ToolCall(
                    "update",
                    "note_update",
                    {"note_id": self.note_id, "content": "The code is 8642."},
                ),
                "delete": ToolCall(
                    "delete", "note_delete", {"note_id": self.note_id}
                ),
            }
            return ProviderReply(
                content="Please confirm deletion." if command == "delete" else "",
                tool_calls=(calls[command],),
            )

    provider = NoteProvider()

    async def exercise() -> None:
        app = create_app(
            provider=provider,
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            ambiguous = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "ambiguous"},
            )
            before = await client.get("/api/settings/notes")
            for command in ("create", "retrieve", "update"):
                response = await client.post(
                    "/api/chat",
                    json={"conversation_id": "main", "content": command},
                )
                assert response.json()["stop_reason"] == "final"
            updated = await client.get(f"/api/settings/notes/{provider.note_id}")
            pending = await client.post(
                "/api/chat", json={"conversation_id": "main", "content": "delete"}
            )
            confirmation = pending.json()["confirmation"]
            deleted = await client.post(
                f"/api/settings/confirmations/{confirmation['id']}/decision",
                json={
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )
            after = await client.get("/api/settings/notes")
            audit = await client.get("/api/settings/audit")

        assert ambiguous.json()["stop_reason"] == "clarification"
        assert ambiguous.json()["chat_content"]["content"] == (
            "What would you like me to save?"
        )
        assert before.json() == {"notes": []}
        assert updated.json()["note"]["content"] == "The code is 8642."
        assert pending.json()["stop_reason"] == "confirmation_pending"
        assert deleted.json()["turn"]["stop_reason"] == "confirmation_accepted"
        assert after.json() == {"notes": []}
        note_events = [
            event
            for event in audit.json()["events"]
            if event["type"] == "application_action_completed"
            and event["details"]["resource_type"] == "note"
        ]
        assert [event["details"]["action"] for event in note_events] == [
            "created",
            "updated",
            "deleted",
        ]
        assert all(event["conversation_id"] == "main" for event in note_events)

    asyncio.run(exercise())

    assert provider.results == [
        "note_create",
        "note_get",
        "note_update",
        "note_delete",
    ]


def test_note_failures_are_truthful_in_chat_and_neutral_in_settings(
    tmp_path: Path,
) -> None:
    class InvalidNoteProvider:
        name = "invalid-note-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                assert request.tool_results[-1].error == "invalid_arguments"
                return ProviderReply(
                    content="I couldn't save that Note because it had no content."
                )
            return ProviderReply(
                tool_calls=(
                    ToolCall("empty-note", "note_create", {"content": ""}),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=InvalidNoteProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            chat = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Save an empty Note."},
            )
            notes = await client.get("/api/settings/notes")
            diagnostic = await client.post(
                "/api/settings/notes", json={"content": " "}
            )

        assert chat.json()["chat_content"]["content"] == (
            "I couldn't save that Note because it had no content."
        )
        assert notes.json() == {"notes": []}
        assert diagnostic.status_code == 422
        assert diagnostic.json()["detail"] == {
            "code": "invalid_note",
            "message": "content must not be empty",
        }

    asyncio.run(exercise())


def test_missing_note_tool_is_reported_as_a_failed_chat_action(
    tmp_path: Path,
) -> None:
    class MissingNoteProvider:
        name = "missing-note-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                result = request.tool_results[-1]
                assert result.error == "executor_error"
                assert result.detail == "Note not found: missing"
                return ProviderReply(content="I couldn't find that Note.")
            return ProviderReply(
                tool_calls=(
                    ToolCall("missing-note", "note_get", {"note_id": "missing"}),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=MissingNoteProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            chat = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Read a missing Note."},
            )
            events = await client.get("/api/events/recent")

        assert chat.json()["chat_content"]["content"] == (
            "I couldn't find that Note."
        )
        failures = [
            event
            for event in events.json()["events"]
            if event["type"] == "tool_execution_failed"
        ]
        assert failures[-1]["details"]["error"] == "executor_error"

    asyncio.run(exercise())


def test_note_audit_failure_reports_that_the_change_was_committed(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        audit_path = tmp_path / "blocked-audit"
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=audit_path,
        )
        audit_path.mkdir()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/settings/notes", json={"content": "Persist this"}
            )
            notes = await client.get("/api/settings/notes")

        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "note_change_notification_failed",
            "operation": "created",
            "note_id": notes.json()["notes"][0]["id"],
            "committed": True,
        }
        assert notes.json()["notes"][0]["content"] == "Persist this"

    asyncio.run(exercise())
