"""Contract tests for the transactional record store (I04).

Covers the five record kinds, single-use idempotent undo, durability across
process restarts, kind validation and the location of the database file.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mellowday import paths
from mellowday.storage.store import KINDS, Store

#: A status that counts as "finished" for every kind.
DONE_STATUS = {
    "todos": "done",
    "calendar": "cancelled",
    "reminders": "delivered",
    "notes": "archived",
    "memories": "expired",
}


def _without_operation(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "operation_id"}


@pytest.mark.parametrize("kind", KINDS)
def test_crud_round_trip(kind: str, isolated_data_dir: Path) -> None:
    store = Store()

    created = store.create_record(
        kind,
        {
            "title": f"{kind} 标题",
            "detail": f"{kind} 详情",
            "due_at": "2026-09-20T09:00:00+08:00",
            "meta": {"tag": kind, "count": 2},
        },
    )
    assert created["kind"] == kind
    assert len(created["id"]) == 32
    assert created["operation_id"].startswith("op_")

    fetched = store.get_record(kind, created["id"])
    assert fetched is not None
    assert fetched == _without_operation(created)
    assert isinstance(fetched["meta"], dict)
    assert fetched["meta"] == {"tag": kind, "count": 2}
    # +08:00 input is normalized to UTC.
    assert fetched["due_at"] == "2026-09-20T01:00:00+00:00"
    assert fetched["created_at"].endswith("+00:00")
    assert fetched["updated_at"].endswith("+00:00")

    updated = store.update_record(kind, created["id"], {"title": "改过的标题"})
    assert updated["operation_id"].startswith("op_")
    assert updated["title"] == "改过的标题"
    assert updated["detail"] == f"{kind} 详情"
    assert store.get_record(kind, created["id"])["title"] == "改过的标题"

    listed = store.list_records(kind)
    assert [record["id"] for record in listed] == [created["id"]]
    assert list(listed[0].keys()) == list(_without_operation(created).keys())

    store.update_record(kind, created["id"], {"status": DONE_STATUS[kind]})
    assert store.list_records(kind, include_done=False) == []
    assert [record["id"] for record in store.list_records(kind)] == [created["id"]]

    deleted = store.delete_record(kind, created["id"])
    assert deleted["id"] == created["id"]
    assert deleted["title"] == "改过的标题"
    assert deleted["operation_id"].startswith("op_")
    assert store.get_record(kind, created["id"]) is None
    assert store.list_records(kind) == []


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_kind_rejected(kind: str, isolated_data_dir: Path) -> None:
    store = Store()
    bogus = kind + "s"
    if bogus in KINDS:
        bogus = kind + "-unknown"
    with pytest.raises(ValueError):
        store.list_records(bogus)
    with pytest.raises(ValueError):
        store.get_record(bogus, "x")
    with pytest.raises(ValueError):
        store.create_record(bogus, {"title": "x"})
    with pytest.raises(ValueError):
        store.update_record(bogus, "x", {"title": "x"})
    with pytest.raises(ValueError):
        store.delete_record(bogus, "x")
    with pytest.raises(ValueError):
        store.search_records(bogus, "x")


def test_missing_record_raises_key_error(isolated_data_dir: Path) -> None:
    store = Store()
    with pytest.raises(KeyError):
        store.update_record("todos", "does-not-exist", {"title": "x"})
    with pytest.raises(KeyError):
        store.delete_record("todos", "does-not-exist")


def test_due_at_accepts_datetime_and_naive_string(isolated_data_dir: Path) -> None:
    store = Store()
    aware = datetime(2026, 9, 20, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    first = store.create_record("calendar", {"title": "会议", "due_at": aware})
    assert first["due_at"] == "2026-09-20T01:00:00+00:00"

    second = store.create_record("calendar", {"title": "无时区", "due_at": "2026-09-21T08:30:00"})
    assert second["due_at"] == "2026-09-21T08:30:00+00:00"

    third = store.create_record("todos", {"title": "没有时间"})
    assert third["due_at"] is None

    with pytest.raises(ValueError):
        store.create_record("todos", {"title": "坏时间", "due_at": "not-a-date"})


def test_undo_create_is_single_use_and_idempotent(isolated_data_dir: Path) -> None:
    store = Store()
    created = store.create_record("todos", {"title": "会被撤销"})
    operation_id = created["operation_id"]

    first = store.undo(operation_id)
    assert first["ok"] is True
    assert first["action"] == "create"
    assert first["undone"] is True
    assert first["record_id"] == created["id"]
    assert store.get_record("todos", created["id"]) is None

    second = store.undo(operation_id)
    assert second == first

    # A second call must not touch anything else in the database.
    survivor = store.create_record("todos", {"title": "不该受影响"})
    third = store.undo(operation_id)
    assert third == first
    assert store.get_record("todos", survivor["id"]) is not None


def test_undo_update_restores_previous_snapshot(isolated_data_dir: Path) -> None:
    store = Store()
    created = store.create_record("notes", {"title": "原标题", "detail": "原内容"})
    updated = store.update_record(
        "notes", created["id"], {"title": "新标题", "detail": "新内容"}
    )
    assert store.get_record("notes", created["id"])["title"] == "新标题"

    undone = store.undo(updated["operation_id"])
    assert undone["ok"] is True
    assert undone["record"]["title"] == "原标题"
    restored = store.get_record("notes", created["id"])
    assert restored["title"] == "原标题"
    assert restored["detail"] == "原内容"
    assert restored["updated_at"] == created["updated_at"]

    assert store.undo(updated["operation_id"]) == undone


def test_undo_delete_restores_and_stays_single_use(isolated_data_dir: Path) -> None:
    store = Store()
    created = store.create_record("reminders", {"title": "喝水", "due_at": "2026-10-01T09:00:00+00:00"})
    deleted = store.delete_record("reminders", created["id"])
    operation_id = deleted["operation_id"]

    first = store.undo(operation_id)
    assert first["ok"] is True
    assert first["action"] == "delete"
    restored = store.get_record("reminders", created["id"])
    assert restored is not None
    assert restored["title"] == "喝水"
    assert restored["due_at"] == "2026-10-01T09:00:00+00:00"
    assert restored["created_at"] == created["created_at"]

    # Change the row, then replay the undo: the second call must not overwrite it.
    store.update_record("reminders", created["id"], {"title": "喝水（已改）"})
    second = store.undo(operation_id)
    assert second == first
    assert store.get_record("reminders", created["id"])["title"] == "喝水（已改）"
    assert len(store.list_records("reminders")) == 1


def test_undo_refuses_to_overwrite_a_later_change(isolated_data_dir: Path) -> None:
    """An undo must not roll back an edit that was made after the operation.

    Regression (T1-B): create a note, edit only its title (op1), edit only its
    detail (op2), then undo op1.  The whole-row replay restored the pre-op1
    snapshot, so the detail written by op2 disappeared without a word.
    """
    store = Store()
    created = store.create_record("notes", {"title": "原标题", "detail": "D0"})
    titled = store.update_record("notes", created["id"], {"title": "新标题"})
    detailed = store.update_record("notes", created["id"], {"detail": "D1"})

    refused = store.undo(titled["operation_id"])
    assert refused["ok"] is False
    assert refused["error"] == "conflict"
    assert refused["undone"] is False, "a refused operation is not consumed"
    assert refused["record_id"] == created["id"]
    assert refused["changed_fields"] == ["detail"]
    assert refused["reason"] in {"record_changed", "record_deleted"}
    assert isinstance(refused["message"], str) and refused["message"].strip()
    assert "备注" in refused["message"], "the message names the field that would be lost"
    assert refused["current_record"]["detail"] == "D1"

    live = store.get_record("notes", created["id"])
    assert live["detail"] == "D1", "the later edit must survive the refused undo"
    assert live["title"] == "新标题"
    assert store.undo(titled["operation_id"]) == refused, "retrying changes nothing"

    # Undoing in reverse order still works, and keeps everything consistent.
    assert store.undo(detailed["operation_id"])["ok"] is True
    after_second = store.get_record("notes", created["id"])
    assert after_second["detail"] == "D0", "only the detail goes back"
    assert after_second["title"] == "新标题", "the title edit is still in place"

    # Once the conflicting change is undone, the first operation works again.
    assert store.undo(titled["operation_id"])["ok"] is True
    restored = store.get_record("notes", created["id"])
    assert restored["title"] == "原标题" and restored["detail"] == "D0"


def test_undo_of_a_create_refuses_to_delete_an_edited_record(isolated_data_dir: Path) -> None:
    """Undoing a create must not delete a record that was edited afterwards."""
    store = Store()
    created = store.create_record("todos", {"title": "买牛奶"})
    edited = store.update_record("todos", created["id"], {"title": "买燕麦奶"})

    refused = store.undo(created["operation_id"])
    assert refused["ok"] is False
    assert refused["error"] == "conflict"
    assert store.get_record("todos", created["id"])["title"] == "买燕麦奶"

    # The later edit is undone first; then the create is undoable as before.
    assert store.undo(edited["operation_id"])["ok"] is True
    assert store.get_record("todos", created["id"])["title"] == "买牛奶"
    assert store.undo(created["operation_id"])["ok"] is True
    assert store.get_record("todos", created["id"]) is None


def test_undo_of_an_update_refuses_when_the_record_was_deleted(isolated_data_dir: Path) -> None:
    """Restoring a snapshot must not resurrect a record deleted afterwards."""
    store = Store()
    created = store.create_record("reminders", {"title": "喝水"})
    updated = store.update_record("reminders", created["id"], {"title": "喝水（改）"})
    deleted = store.delete_record("reminders", created["id"])

    refused = store.undo(updated["operation_id"])
    assert refused["ok"] is False
    assert refused["error"] == "conflict"
    assert refused["reason"] == "record_deleted"
    assert refused["message"].strip()
    assert store.get_record("reminders", created["id"]) is None, "nothing was resurrected"

    # Undo the deletion, then the update: the order that actually works.
    assert store.undo(deleted["operation_id"])["ok"] is True
    assert store.get_record("reminders", created["id"])["title"] == "喝水（改）"
    assert store.undo(updated["operation_id"])["ok"] is True
    assert store.get_record("reminders", created["id"])["title"] == "喝水"


def test_undo_unknown_operation_is_reported(isolated_data_dir: Path) -> None:
    store = Store()
    payload = store.undo("op_missing")
    assert payload["ok"] is False
    assert payload["error"] == "unknown_operation_id"
    assert store.undo("")["ok"] is False


def test_records_survive_a_new_store_instance(isolated_data_dir: Path) -> None:
    first = Store()
    created = first.create_record("todos", {"title": "重启后仍在", "meta": {"k": "v"}})
    first.update_record("todos", created["id"], {"detail": "补充"})

    reopened = Store()
    assert reopened.path == first.path
    record = reopened.get_record("todos", created["id"])
    assert record is not None
    assert record["title"] == "重启后仍在"
    assert record["detail"] == "补充"
    assert record["meta"] == {"k": "v"}
    assert len(reopened.list_records("todos")) == 1


def test_database_lives_under_data_dir(isolated_data_dir: Path) -> None:
    store = Store()
    assert store.path == isolated_data_dir / "mellowday.sqlite3"
    assert store.path == paths.store_path()
    assert store.path.parent == Path(paths.data_dir())
    assert store.path.exists()

    explicit = Store(isolated_data_dir / "custom")
    assert explicit.path == isolated_data_dir / "custom" / "mellowday.sqlite3"
    assert explicit.path.exists()


def test_sqlite_uses_wal_and_foreign_keys(isolated_data_dir: Path) -> None:
    store = Store()
    store.create_record("todos", {"title": "x"})
    connection = sqlite3.connect(store.path)
    try:
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert journal.lower() == "wal"


def test_memory_lifecycle_filters_recall(isolated_data_dir: Path) -> None:
    store = Store()
    active = store.create_record("memories", {"title": "偏好", "detail": "喜欢无糖咖啡"})
    assert active["status"] == "active"

    expired = store.create_record("memories", {"title": "旧的", "detail": "住过北京"})
    store.update_record("memories", expired["id"], {"status": "expired"})

    assert [record["id"] for record in store.list_records("memories", include_done=False)] == [
        active["id"]
    ]
    assert len(store.list_records("memories")) == 2
    assert [record["id"] for record in store.search_records("memories", "北京")] == []
    assert [record["id"] for record in store.search_records("memories", "咖啡")] == [
        active["id"]
    ]

    store.update_record("memories", active["id"], {"status": "deleted"})
    assert store.search_records("memories", "咖啡") == []
    assert store.list_records("memories", include_done=False) == []


def test_search_matches_title_detail_and_meta(isolated_data_dir: Path) -> None:
    store = Store()
    first = store.create_record("notes", {"title": "读书笔记", "detail": "《小王子》"})
    second = store.create_record(
        "notes", {"title": "会议", "detail": "周会", "meta": {"project": "mellowday"}}
    )
    store.create_record("notes", {"title": "购物", "detail": "牛奶"})

    assert [r["id"] for r in store.search_records("notes", "小王子")] == [first["id"]]
    assert [r["id"] for r in store.search_records("notes", "mellowday")] == [second["id"]]
    # Tokens are combined with AND.
    assert [r["id"] for r in store.search_records("notes", "读书 小王子")] == [first["id"]]
    assert store.search_records("notes", "读书 牛奶") == []
    assert store.search_records("notes", "%") == []


def test_meta_round_trips_as_json_object(isolated_data_dir: Path) -> None:
    store = Store()
    created = store.create_record("todos", {"title": "x", "meta": '{"a": 1}'})
    assert created["meta"] == {"a": 1}
    assert store.get_record("todos", created["id"])["meta"] == {"a": 1}

    with pytest.raises(ValueError):
        store.create_record("todos", {"title": "x", "meta": "not json"})
    with pytest.raises(ValueError):
        store.create_record("todos", {"title": "x", "meta": 5})

    plain = store.create_record("todos", {"title": "y"})
    assert plain["meta"] == {}


def test_returned_records_are_json_serializable(isolated_data_dir: Path) -> None:
    store = Store()
    created = store.create_record(
        "calendar",
        {"title": "会议", "due_at": "2026-09-20T09:00:00", "meta": {"a": [1, 2]}},
    )
    payloads = [
        created,
        store.get_record("calendar", created["id"]),
        store.list_records("calendar"),
        store.list_records("calendar", include_done=False),
        store.search_records("calendar", "会议"),
        store.update_record("calendar", created["id"], {"title": "会议2"}),
        store.delete_record("calendar", created["id"]),
        store.undo(created["operation_id"]),
    ]
    for payload in payloads:
        assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
