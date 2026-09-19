"""The restricted tool-result read over HTTP (CONTRACTS.md 6ter.1 / 6ter.2).

A shortened tool result keeps its whole original in the session artifact
directory and its trace entry carries the bare ref of that artifact. This
endpoint is how the web surface follows the reference, so the tests are
behaviour level: real paging and query reads over a real stored artifact, real
error mapping, cross-session isolation - and the endpoint must never turn into
a general file read or answer 500.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mellowday import paths
from mellowday.runtime import sessions as session_store
from mellowday.storage.store import Store
from mellowday.web_app.app import create_app

SESSION = "api-session"
OTHER = "other-session"

HEAD = "笔记开头-"
NEEDLE = "这里是要找的段落"
LONG_TEXT = HEAD + "甲" * 9000 + NEEDLE + "乙" * 900 + "-笔记结尾"


@pytest.fixture
def app(tmp_path):
    return create_app(store=Store(data_dir=tmp_path / "data"))


def api(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test"
    )


def url(session_id: str, ref: str) -> str:
    return f"/api/sessions/{session_id}/tool-results/{ref}"


@pytest.mark.anyio
async def test_a_stored_result_is_paged_over_http(app):
    """One request returns one bounded window and says where to continue."""
    artifact = session_store.save_tool_artifact(SESSION, "list_notes", LONG_TEXT)
    ref = artifact["ref"]
    assert artifact["chars"] == len(LONG_TEXT)

    async with api(app) as client:
        first = await client.get(url(SESSION, ref), params={"limit": 100})
        assert first.status_code == 200
        page = first.json()
        assert page["ok"] is True and page["ref"] == ref
        assert page["total_chars"] == len(LONG_TEXT)
        assert page["text"] == LONG_TEXT[:100]
        assert page["returned"] == 100 and page["offset"] == 0
        assert page["has_more"] is True and page["next_offset"] == 100

        second = await client.get(url(SESSION, ref), params={"limit": 100, "offset": 100})
        assert second.json()["text"] == LONG_TEXT[100:200]
        assert second.json()["next_offset"] == 200

        # The default window is the runtime default, not the whole result.
        default = await client.get(url(SESSION, ref))
        assert default.json()["text"] == LONG_TEXT[: session_store.ARTIFACT_DEFAULT_CHARS]
        assert default.json()["has_more"] is True

        # The last page reports the end instead of pretending there is more.
        tail = await client.get(url(SESSION, ref), params={"offset": len(LONG_TEXT) - 20})
        assert tail.json()["text"] == LONG_TEXT[-20:]
        assert tail.json()["has_more"] is False
        assert tail.json()["next_offset"] is None


@pytest.mark.anyio
async def test_a_query_read_locates_the_passage(app):
    """query= returns the passage around the match, or says it is not there."""
    artifact = session_store.save_tool_artifact(SESSION, "list_notes", LONG_TEXT)
    ref = artifact["ref"]

    async with api(app) as client:
        found = await client.get(url(SESSION, ref), params={"query": NEEDLE, "limit": 200})
        assert found.status_code == 200
        payload = found.json()
        assert payload["ok"] is True
        assert payload["match_offset"] == LONG_TEXT.index(NEEDLE)
        assert NEEDLE in payload["text"]
        assert payload["total_chars"] == len(LONG_TEXT)
        window = payload["window_end"] - payload["window_start"]
        assert window <= session_store.ARTIFACT_MAX_CHARS
        assert payload["text"] == LONG_TEXT[payload["window_start"]:payload["window_end"]]

        missing = await client.get(url(SESSION, ref), params={"query": "没有这段内容"})
        assert missing.status_code == 404
        assert missing.json()["ok"] is False
        assert missing.json()["error"] == "not_found"

        empty = await client.get(url(SESSION, ref), params={"query": ""})
        assert empty.status_code == 400
        assert empty.json()["error"] == "invalid_arguments"


@pytest.mark.anyio
async def test_bad_refs_are_reported_and_never_500(app):
    """A bad reference is data, not a crash - and never a file read."""
    artifact = session_store.save_tool_artifact(SESSION, "list_notes", LONG_TEXT)
    ref = artifact["ref"]

    async with api(app) as client:
        unknown = await client.get(url(SESSION, "1700000000000-list_notes-deadbeef"))
        assert unknown.status_code == 404
        assert unknown.json()["error"] == "unknown_ref"
        assert unknown.json()["detail"]

        dotted = await client.get(url(SESSION, "mellowday.sqlite3"))
        assert dotted.status_code == 400
        assert dotted.json()["error"] == "invalid_ref"

        # The session id is validated here exactly like everywhere else.
        bad_session = await client.get(url("a%20b", ref))
        assert bad_session.status_code == 400

        # Traversal attempts are refused; the response is never a database file.
        for raw in ("..%2F..%2Fmellowday.sqlite3", "..%5C..%5Cmellowday.sqlite3", "%2E%2E"):
            response = await client.get(f"/api/sessions/{SESSION}/tool-results/{raw}")
            assert response.status_code != 500, raw
            assert "SQLite format" not in response.text, raw


@pytest.mark.anyio
async def test_another_sessions_result_is_invisible(app):
    """A ref resolves inside its own session only (6ter.1)."""
    mine = session_store.save_tool_artifact(SESSION, "list_notes", "我的原文")
    theirs = session_store.save_tool_artifact(OTHER, "list_notes", "别人的原文")

    async with api(app) as client:
        assert (await client.get(url(SESSION, mine["ref"]))).status_code == 200
        crossed = await client.get(url(SESSION, theirs["ref"]))
        assert crossed.status_code == 404
        assert crossed.json()["error"] == "unknown_ref"
        assert "别人的原文" not in crossed.text


@pytest.mark.anyio
async def test_an_unknown_or_deleted_session_answers_404_without_side_effects(app):
    """Following a ref of a session with no artifacts must not create any.

    The artifact layer creates its directory on demand, so a lookup for an
    unknown session would leave an empty tree behind - and a deleted session must
    stay deleted even when someone follows a stale reference.
    """
    root = paths.data_dir() / session_store.ARTIFACT_DIR_NAME
    assert not root.exists()

    async with api(app) as client:
        absent = await client.get(url("never-existed", "1700000000000-list_notes-deadbeef"))
        assert absent.status_code == 404
        assert absent.json()["ok"] is False
        assert absent.json()["error"] == "unknown_ref"
        assert absent.json()["detail"]
    assert not root.exists(), "answering must not create the artifact directory"

    # A real artifact, then the session is gone: the stale ref answers 404 and
    # the deletion is not undone by the read.
    artifact = session_store.save_tool_artifact(SESSION, "list_notes", LONG_TEXT)
    directory = Path(artifact["path"]).parent
    async with api(app) as client:
        assert (await client.get(url(SESSION, artifact["ref"]))).status_code == 200
    assert session_store.delete_tool_artifacts(SESSION) == 1
    assert not directory.exists()

    async with api(app) as client:
        stale = await client.get(url(SESSION, artifact["ref"]))
        assert stale.status_code == 404
        assert stale.json()["error"] == "unknown_ref"
    assert not directory.exists(), "a read must not resurrect the session's directory"
    assert not list(root.glob("**/*.txt"))
