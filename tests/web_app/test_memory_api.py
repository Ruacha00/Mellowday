"""Memory behavior at the complete Web App boundary."""

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest, ToolCall
from mellowday.web_app import create_app


def test_explicit_chat_request_saves_inspectable_memory_directly(
    tmp_path: Path,
) -> None:
    class ExplicitMemoryProvider:
        name = "memory-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                saved = request.tool_results[-1].result["memory"]
                return ProviderReply(content=f"I'll remember: {saved['content']}")
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "remember-explicit",
                        "memory_remember",
                        {
                            "content": "I prefer concise replies.",
                            "kind": "preference",
                            "provenance": "explicit",
                        },
                    ),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=ExplicitMemoryProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            chat = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "Remember that I prefer concise replies.",
                },
            )
            listed = await client.get("/api/settings/memories")
            capabilities = await client.get("/api/settings/capabilities")

        assert chat.status_code == 200
        assert chat.json()["chat_content"]["content"] == (
            "I'll remember: I prefer concise replies."
        )
        memories = listed.json()["memories"]
        assert len(memories) == 1
        assert memories[0]["content"] == "I prefer concise replies."
        assert memories[0]["kind"] == "preference"
        assert memories[0]["provenance"] == "explicit"
        assert memories[0]["source_conversation_id"] == "main"
        assert {tool["name"] for tool in capabilities.json()["tools"]} >= {
            "memory_remember"
        }

    asyncio.run(exercise())


def test_automatic_memory_uses_a_conservative_evidence_boundary(
    tmp_path: Path,
) -> None:
    candidates = {
        "I use Python for work.": {
            "content": "I use Python for work.",
            "kind": "fact",
            "evidence": "I use Python for work.",
        },
        "I feel sad today.": {
            "content": "I feel sad today.",
            "kind": "fact",
            "evidence": "I feel sad today.",
        },
        "I only eat moon rocks — just kidding.": {
            "content": "I only eat moon rocks.",
            "kind": "preference",
            "evidence": "I only eat moon rocks — just kidding.",
        },
        "The cafe closes at nine.": {
            "content": "I prefer tea.",
            "kind": "preference",
            "evidence": "The cafe closes at nine.",
        },
        "I went to the cafe.": {
            "content": "I prefer tea.",
            "kind": "preference",
            "evidence": "I prefer tea.",
        },
    }

    class AutomaticMemoryProvider:
        name = "automatic-memory-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                return ProviderReply(content="Candidate considered.")
            user_message = request.messages[-1].content
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        f"learn-{len(request.messages)}",
                        "memory_learn",
                        candidates[user_message],
                    ),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=AutomaticMemoryProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for user_message in candidates:
                response = await client.post(
                    "/api/chat",
                    json={"conversation_id": "main", "content": user_message},
                )
                assert response.status_code == 200
            listed = await client.get("/api/settings/memories")

        assert [memory["content"] for memory in listed.json()["memories"]] == [
            "I use Python for work."
        ]
        assert listed.json()["memories"][0]["provenance"] == "automatic"

    asyncio.run(exercise())


def test_later_turn_receives_relevant_memory_without_unrelated_records(
    tmp_path: Path,
) -> None:
    class RecallProvider:
        name = "memory-recall-script"

        def __init__(self) -> None:
            self.instructions: dict[str, str] = {}

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                return ProviderReply(content="Saved.")
            message = request.messages[-1].content
            if message.startswith("Remember"):
                content = message.removeprefix("Remember ")
                kind = "fact" if "Python" in content else "preference"
                return ProviderReply(
                    tool_calls=(
                        ToolCall(
                            f"remember-{kind}",
                            "memory_remember",
                            {
                                "content": content,
                                "kind": kind,
                                "provenance": "explicit",
                            },
                        ),
                    )
                )
            self.instructions[message] = request.system_instructions
            return ProviderReply(content="Answered with relevant context.")

    provider = RecallProvider()

    async def exercise() -> None:
        app = create_app(
            provider=provider,
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for content in (
                "Remember I use Python for work.",
                "Remember I prefer window seats when flying.",
                "What language do I use for work?",
                "What should I buy for my garden?",
            ):
                response = await client.post(
                    "/api/chat",
                    json={"conversation_id": "main", "content": content},
                )
                assert response.status_code == 200

        relevant = provider.instructions["What language do I use for work?"]
        unrelated = provider.instructions["What should I buy for my garden?"]
        assert "I use Python for work." in relevant
        assert "window seats" not in relevant
        assert "I use Python for work." not in unrelated
        assert "window seats" not in unrelated

    asyncio.run(exercise())


def test_settings_corrects_and_deletes_memory_after_restart(
    tmp_path: Path,
) -> None:
    class SaveProvider:
        name = "save-memory-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                return ProviderReply(content="Saved.")
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "save-memory",
                        "memory_remember",
                        {
                            "content": "I prefer concise replies.",
                            "kind": "preference",
                            "provenance": "explicit",
                        },
                    ),
                )
            )

    async def exercise() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        first_app = create_app(
            provider=SaveProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Remember this."},
            )
            created = (await client.get("/api/settings/memories")).json()[
                "memories"
            ][0]
            reset_request = await client.post(
                "/api/conversations/main/reset-confirmation"
            )
            reset_confirmation = reset_request.json()["confirmation"]
            reset = await client.post(
                "/api/conversations/main/reset",
                json={
                    "confirmation_id": reset_confirmation["id"],
                    "decision": "accept",
                    "binding": reset_confirmation["binding"],
                },
            )
            assert reset.json()["removed_messages"] == 2

        restarted = create_app(
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            persisted = await client.get(
                "/api/settings/memories", params={"q": "concise"}
            )
            corrected = await client.patch(
                f"/api/settings/memories/{created['id']}",
                json={"content": "I prefer detailed replies."},
            )
            old_search = await client.get(
                "/api/settings/memories", params={"q": "concise"}
            )
            new_search = await client.get(
                "/api/settings/memories", params={"q": "detailed"}
            )
            requested = await client.post(
                f"/api/settings/memories/{created['id']}/delete-confirmation"
            )
            confirmation = requested.json()["confirmation"]
            deleted = await client.request(
                "DELETE",
                f"/api/settings/memories/{created['id']}",
                json={
                    "confirmation_id": confirmation["id"],
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )
            remaining = await client.get("/api/settings/memories")
            audit = await client.get("/api/settings/audit")

        assert persisted.json()["memories"] == [created]
        assert corrected.json()["memory"]["content"] == (
            "I prefer detailed replies."
        )
        assert corrected.json()["memory"]["provenance"] == "explicit"
        assert old_search.json() == {"memories": []}
        assert new_search.json()["memories"] == [corrected.json()["memory"]]
        assert deleted.json()["deleted_memory"]["id"] == created["id"]
        assert remaining.json() == {"memories": []}
        memory_actions = [
            event["details"]["action"]
            for event in audit.json()["events"]
            if event["type"] == "application_action_completed"
            and event["details"]["resource_type"] == "memory"
        ]
        assert memory_actions == ["updated", "deleted"]

    asyncio.run(exercise())


def test_natural_forgetting_uses_the_shared_service_and_action_policy(
    tmp_path: Path,
) -> None:
    class ForgetProvider:
        name = "forget-memory-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                result = request.tool_results[-1]
                if result.name == "memory_search":
                    memory_id = result.result["memories"][0]["id"]
                    return ProviderReply(
                        content="Please confirm forgetting this Memory.",
                        tool_calls=(
                            ToolCall(
                                "forget-memory",
                                "memory_forget",
                                {"memory_id": memory_id},
                            ),
                        ),
                    )
                if result.name == "memory_forget":
                    return ProviderReply(content="I forgot that Memory.")
                return ProviderReply(content="Saved.")
            message = request.messages[-1].content
            if message.startswith("Remember"):
                return ProviderReply(
                    tool_calls=(
                        ToolCall(
                            "remember-memory",
                            "memory_remember",
                            {
                                "content": "I prefer window seats when flying.",
                                "kind": "preference",
                                "provenance": "explicit",
                            },
                        ),
                    )
                )
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "find-memory", "memory_search", {"query": "window seats"}
                    ),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=ForgetProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Remember this."},
            )
            pending = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "Forget my window-seat preference.",
                },
            )
            before = await client.get("/api/settings/memories")
            confirmation = pending.json()["confirmation"]
            accepted = await client.post(
                f"/api/settings/confirmations/{confirmation['id']}/decision",
                json={
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )
            after = await client.get("/api/settings/memories")

        assert pending.json()["stop_reason"] == "confirmation_pending"
        assert pending.json()["confirmation"]["binding"]["tool"] == (
            "memory_forget"
        )
        assert len(before.json()["memories"]) == 1
        assert accepted.json()["turn"]["stop_reason"] == "confirmation_accepted"
        assert accepted.json()["turn"]["chat_content"]["content"] == (
            "I forgot that Memory."
        )
        assert after.json() == {"memories": []}

    asyncio.run(exercise())
