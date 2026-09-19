import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from mellowday.personal_assistant.turn_memory import TurnMemory
from mellowday.storage.store import Store


def candidate(text="我长期吃素", explicit=False):
    return json.dumps({"candidate": {"content": text, "label": "饮食偏好", "kind": "preference",
                                    "evidence": text, "explicit": explicit}}, ensure_ascii=False)


@pytest.mark.anyio
async def test_explicit_is_current_turn_only_and_atomic_once():
    store = Store()
    query, confirm = AsyncMock(return_value=candidate(explicit=True)), AsyncMock(return_value=False)
    turn = TurnMemory(store, "chat", 1, "记住，我长期吃素", query, confirm)
    first, second = await asyncio.gather(turn.process(), turn.process())
    assert first["ok"] and first == second
    assert len(store.list_records("memories")) == 1
    assert query.await_count == 1
    confirm.assert_not_awaited()
    assert json.loads(query.call_args.args[1]) == {"current_user_message": "记住，我长期吃素"}
    assert store.undo(first["operation_id"])["ok"]
    replay = await TurnMemory(store, "chat", 1, "记住，我长期吃素", query, confirm).process()
    assert not replay["ok"] and not store.list_records("memories")


@pytest.mark.anyio
async def test_automatic_memory_requires_confirmation_rejection_never_replayed():
    store = Store()
    query, confirm = AsyncMock(return_value=candidate()), AsyncMock(return_value=False)
    result = await TurnMemory(store, "chat", 1, "我长期吃素", query, confirm).process()
    assert result["error"] == "memory_declined"
    replay = await TurnMemory(store, "chat", 1, "我长期吃素", query, confirm).process()
    assert replay == result and query.await_count == 1 and confirm.await_count == 1
    assert not store.list_records("memories")


@pytest.mark.anyio
async def test_evidence_from_history_cannot_be_saved():
    store = Store()
    query, confirm = AsyncMock(return_value=candidate(explicit=True)), AsyncMock(return_value=True)
    result = await TurnMemory(store, "chat", 1, "记住刚才说的那个", query, confirm).process()
    assert not result["ok"]
    confirm.assert_not_awaited()
    assert not store.list_records("memories")


@pytest.mark.anyio
async def test_conflict_changed_during_confirmation_is_not_overwritten():
    store = Store()
    original = store.create_record("memories", {"title": "饮食偏好", "detail": "不吃香菜"})
    async def confirm(_):
        store.update_record("memories", original["id"], {"detail": "新的手动设置"})
        return True
    result = await TurnMemory(store, "chat", 1, "我长期吃素", AsyncMock(return_value=candidate()), confirm).process()
    assert result["error"] == "memory_changed"
    assert store.get_record("memories", original["id"])["detail"] == "新的手动设置"


@pytest.mark.anyio
async def test_cancelled_confirmation_cannot_write_afterwards():
    store = Store()
    async def confirm(_):
        raise asyncio.CancelledError
    query = AsyncMock(return_value=candidate())
    with pytest.raises(asyncio.CancelledError):
        await TurnMemory(store, "chat", 1, "我长期吃素", query, confirm).process()
    assert (await TurnMemory(store, "chat", 1, "我长期吃素", query, confirm).process())["error"] == "cancelled"
    assert not store.list_records("memories")


@pytest.mark.anyio
async def test_new_round_can_save_same_fact_after_user_reexpresses_it():
    store = Store()
    query, confirm = AsyncMock(return_value=candidate()), AsyncMock(return_value=True)
    first = await TurnMemory(store, "chat", 1, "我长期吃素", query, confirm).process()
    store.delete_record("memories", first["id"])
    second = await TurnMemory(store, "chat", 2, "我长期吃素", query, confirm).process()
    assert second["ok"] and first["id"] != second["id"]

@pytest.mark.anyio
@pytest.mark.parametrize('text', [
    '记住我喜欢茶，另外我长期吃素',
    '记住我喜欢茶 另外我长期吃素',
    '有人说“记住我长期吃素”，这只是一段引用',
    '你记住我长期吃素了吗？',
    'Do you remember 我长期吃素?',
])
async def test_explicit_flag_does_not_authorize_other_fact_or_recall_question(text):
    store = Store()
    confirm = AsyncMock(return_value=False)
    query = AsyncMock(return_value=candidate(explicit=True))
    result = await TurnMemory(store, 'chat', 1, text, query, confirm).process()
    assert result['error'] == 'memory_declined'
    confirm.assert_awaited_once()
    assert not store.list_records('memories')


@pytest.mark.anyio
@pytest.mark.parametrize('text', ['请记住：我长期吃素。', '记住我长期吃素，另外我喜欢茶'])
async def test_explicit_consent_applies_only_to_exact_first_fact(text):
    store = Store()
    confirm = AsyncMock(return_value=False)
    result = await TurnMemory(store, 'chat', 1, text,
                              AsyncMock(return_value=candidate(explicit=True)), confirm).process()
    assert result['ok']
    confirm.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('status', ['expired', 'deleted', 'superseded'])
async def test_replay_inactive_memory_never_returns_stale_success(status):
    store = Store()
    query, confirm = AsyncMock(return_value=candidate(explicit=True)), AsyncMock(return_value=True)
    first = await TurnMemory(store, 'chat', 1, '记住我长期吃素', query, confirm).process()
    store.update_record('memories', first['id'], {'status': status})
    replay = await TurnMemory(store, 'chat', 1, '记住我长期吃素', query, confirm).process()
    assert replay['error'] == 'memory_removed'
    assert query.await_count == 1
    assert store.get_record('memories', first['id'])['status'] == status


@pytest.mark.anyio
async def test_replay_changed_memory_does_not_return_obsolete_record():
    store = Store()
    query, confirm = AsyncMock(return_value=candidate(explicit=True)), AsyncMock(return_value=True)
    first = await TurnMemory(store, 'chat', 1, '记住我长期吃素', query, confirm).process()
    store.update_record('memories', first['id'], {'detail': '已更新的饮食偏好'})
    replay = await TurnMemory(store, 'chat', 1, '记住我长期吃素', query, confirm).process()
    assert replay['error'] == 'memory_changed'
    assert query.await_count == 1
    assert store.get_record('memories', first['id'])['detail'] == '已更新的饮食偏好'
