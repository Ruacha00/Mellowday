"""T1-B: an undo that would roll back a later change is refused, visibly.

Behaviour level: the real app, the real SQLite store and the same HTTP request
the management page sends.  The page prints the response "detail" field in the
notice line (app.js requestJson -> describeError), so the conflict reason is
asserted exactly where the page reads it, and the row is read back to prove that
the change made *after* the operation is still there.
"""
from __future__ import annotations

import httpx
import pytest

from mellowday.storage.store import Store
from mellowday.web_app.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(store=Store(data_dir=tmp_path / "data"))


def api(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test"
    )


async def records(client: httpx.AsyncClient, kind: str) -> list[dict]:
    return (await client.get(f"/api/records/{kind}")).json()["records"]


@pytest.mark.anyio
async def test_a_conflicting_undo_is_refused_with_a_reason_the_page_can_print(app):
    """Edit the title, then the detail, then undo the title edit: refuse + explain."""
    async with api(app) as client:
        created = (
            await client.post("/api/records/notes", json={"title": "原标题", "detail": "D0"})
        ).json()
        record_id = created["id"]
        op_title = (
            await client.patch(f"/api/records/notes/{record_id}", json={"title": "新标题"})
        ).json()["operation_id"]
        op_detail = (
            await client.patch(f"/api/records/notes/{record_id}", json={"detail": "D1"})
        ).json()["operation_id"]

        response = await client.post(f"/api/records/undo/{op_title}")
        assert response.status_code == 409, "a refusal must be visible, not a silent 200"
        payload = response.json()
        assert payload["ok"] is False
        assert payload["error"] == "conflict"
        assert payload["changed_fields"] == ["detail"]
        assert payload["undone"] is False
        # This is the string the page puts into the #records-notice line.
        detail = payload.get("detail")
        assert isinstance(detail, str) and detail.strip()
        assert detail == payload["message"]
        assert "撤销被拒绝" in detail
        assert "备注" in detail, "the page must name the change that would be lost"

        current = next(r for r in await records(client, "notes") if r["id"] == record_id)
        assert current["detail"] == "D1", "the later edit is still there"
        assert current["title"] == "新标题"

        # The order that works: undo the later change, then the earlier one.
        assert (await client.post(f"/api/records/undo/{op_detail}")).status_code == 200
        assert (await client.post(f"/api/records/undo/{op_title}")).status_code == 200
        final = next(r for r in await records(client, "notes") if r["id"] == record_id)
        assert final["title"] == "原标题"
        assert final["detail"] == "D0"


@pytest.mark.anyio
async def test_a_conflict_does_not_burn_either_operation(app):
    """A refused undo consumes nothing: both operations stay undoable in order."""
    async with api(app) as client:
        created = (await client.post("/api/records/todos", json={"title": "买牛奶"})).json()
        record_id = created["id"]
        op_edit = (
            await client.patch(f"/api/records/todos/{record_id}", json={"title": "买燕麦奶"})
        ).json()["operation_id"]

        first = await client.post(f"/api/records/undo/{created['operation_id']}")
        assert first.status_code == 409
        again = await client.post(f"/api/records/undo/{created['operation_id']}")
        assert again.status_code == 409 and again.json()["changed_fields"] == ["title"]

        # The later edit is untouched and still undoable, and then so is the create.
        undone = await client.post(f"/api/records/undo/{op_edit}")
        assert undone.status_code == 200 and undone.json()["ok"] is True
        stored = next(r for r in await records(client, "todos") if r["id"] == record_id)
        assert stored["title"] == "买牛奶"
        removed = await client.post(f"/api/records/undo/{created['operation_id']}")
        assert removed.status_code == 200 and removed.json()["ok"] is True
        assert not [r for r in await records(client, "todos") if r["id"] == record_id]


@pytest.mark.anyio
async def test_an_uncontended_undo_keeps_its_old_response_shape(app):
    """The single-write path (and the unknown-operation path) is unchanged."""
    async with api(app) as client:
        created = (
            await client.post("/api/records/reminders", json={"title": "喝水", "detail": "D0"})
        ).json()
        record_id = created["id"]
        edited = (
            await client.patch(f"/api/records/reminders/{record_id}", json={"detail": "D1"})
        ).json()

        response = await client.post(f"/api/records/undo/{edited['operation_id']}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True and payload["undone"] is True
        assert payload["record"]["detail"] == "D0"
        stored = next(r for r in await records(client, "reminders") if r["id"] == record_id)
        assert stored["detail"] == "D0"

        unknown = await client.post("/api/records/undo/op_missing")
        assert unknown.status_code == 200
        assert unknown.json() == {
            "ok": False,
            "error": "unknown_operation_id",
            "operation_id": "op_missing",
        }
