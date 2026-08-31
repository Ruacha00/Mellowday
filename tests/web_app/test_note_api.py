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


def test_chat_creates_clear_notes_and_clarifies_ambiguous_requests(
    tmp_path: Path,
) -> None:
    class NoteProvider:
        name = "note-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                if request.tool_results[-1].error == "ambiguous_intent":
                    return ProviderReply(content="What would you like me to save?")
                return ProviderReply(content="I saved that as a Note.")
            command = request.messages[-1].content
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        command,
                        "note_create",
                        {"title": "Door code", "content": "The code is 2468."},
                        intent_clarity=(
                            "ambiguous" if command == "Save a note." else "clear"
                        ),
                    ),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=NoteProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            ambiguous = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Save a note."},
            )
            before = await client.get("/api/settings/notes")
            clear = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "Save the door code as a note.",
                },
            )
            after = await client.get("/api/settings/notes")
            audit = await client.get("/api/settings/audit")

        assert ambiguous.json()["stop_reason"] == "clarification"
        assert ambiguous.json()["chat_content"]["content"] == (
            "What would you like me to save?"
        )
        assert before.json() == {"notes": []}
        assert clear.json()["stop_reason"] == "final"
        assert clear.json()["chat_content"]["content"] == "I saved that as a Note."
        assert len(after.json()["notes"]) == 1
        note_events = [
            event
            for event in audit.json()["events"]
            if event["type"] == "application_action_completed"
            and event["details"]["resource_type"] == "note"
        ]
        assert note_events[0]["conversation_id"] == "main"

    asyncio.run(exercise())


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
