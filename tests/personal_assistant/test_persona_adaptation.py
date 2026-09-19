"""Real persistence and request boundaries for limited persona evolution."""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mellowday.personal_assistant import persona, persona_adaptation as pa
from mellowday.web_app.persona_routes import router


def provider(scene='讨论技术问题', behavior='先说明结论', quote='以后讨论技术问题先说明结论', explicit=True, allowed=True):
    candidate = dict(scene=scene, behavior=behavior, example='', quote=quote, explicit=explicit)
    return AsyncMock(side_effect=[json.dumps({'candidate': candidate}), json.dumps({'allowed': allowed})])


async def learn(turn='1', **kwargs):
    text = kwargs.get('quote', '以后讨论技术问题先说明结论')
    query = provider(**kwargs)
    return await pa.adapt_turn('session', turn, text, query)


def test_legacy_core_and_read_only_empty():
    old = {k: v for k, v in persona.DEFAULT_PERSONA.items() if k != 'examples'}
    assert persona.save_persona(old)['examples'] == ''
    assert pa.snapshot()['rules'] == []
    assert not pa._path().exists()


@pytest.mark.anyio
async def test_learning_is_traceable_once_and_core_immutable():
    before = persona.load_persona()
    result = await learn()
    assert result['status'] == 'applied'
    rule = pa.snapshot()['rules'][0]
    assert rule['source'][0]['turn_id'] == '1'
    assert rule['source'][0]['quote'] == '以后讨论技术问题先说明结论'
    query = AsyncMock()
    assert (await pa.adapt_turn('session', '1', 'another message', query))['status'] == 'already_processed'
    query.assert_not_called()
    assert persona.load_persona() == before
    assert '先说明结论' in pa.adaptation_prompt('讨论技术问题')
    assert pa.adaptation_prompt('我想吃面条') == ''


@pytest.mark.anyio
async def test_temporary_unsupported_and_unsafe_candidates():
    assert (await learn(quote='这次简单点'))['status'] == 'no_candidate'
    assert (await learn('2', allowed=False))['status'] == 'rejected'
    query = provider(quote='以后用其他名字')
    assert (await pa.adapt_turn('session', '3', '你好', query))['status'] == 'no_candidate'
    assert not pa.snapshot()['rules']


@pytest.mark.anyio
async def test_pause_lock_undo_and_reset():
    pa.set_paused(True)
    assert (await learn())['status'] == 'paused'
    pa.set_paused(False)
    result = await learn('2')
    rule_id = result['rule_id']
    pa.set_locked(rule_id, True)
    assert (await learn('3', behavior='使用简短表达'))['status'] == 'locked'
    pa.set_locked(rule_id, False)
    pa.undo(rule_id)
    assert not pa.snapshot()['rules'][0]['enabled']
    assert (await learn('4'))['status'] == 'suppressed'
    pa.reset()
    assert pa.snapshot()['history'][-1]['action'] == 'reset'


@pytest.mark.anyio
async def test_daily_budget_and_core_change_even_for_locked_rules():
    assert (await learn())['status'] == 'applied'
    assert (await learn('2', scene='表达建议'))['status'] == 'applied'
    assert (await learn('3', scene='问候'))['status'] == 'budget'
    pa.set_locked(pa.snapshot()['rules'][0]['id'], True)
    persona.save_persona({**persona.load_persona(), 'character': '严肃而清晰'})
    assert all(not rule['enabled'] for rule in pa.snapshot()['rules'])
    assert pa.adaptation_prompt('讨论技术问题') == ''


@pytest.mark.anyio
async def test_implicit_feedback_requires_independent_evidence():
    for turn, text in [('1', '解释太长了'), ('2', '解释太长了'), ('3', '刚才有点啰嗦')]:
        assert (await learn(turn, quote=text, explicit=False))['status'] == 'awaiting_evidence'
    result = await learn('4', quote='文字有点多', explicit=False)
    assert result['status'] == 'applied'
    assert len(pa.snapshot()['rules'][0]['source']) == 3


@pytest.mark.anyio
async def test_inflight_core_and_setting_change_discard_candidate():
    query = provider()
    async def changed(system, text):
        answer = await query(system, text)
        pa.set_paused(True)
        return answer
    assert (await pa.adapt_turn('s', 't', '以后讨论技术问题先说明结论', changed))['status'] == 'stale'
    assert not pa.snapshot()['rules']


@pytest.mark.anyio
async def test_api_validation_and_persistence():
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/persona/adaptation')).json()['version'] == 0
        assert (await client.put('/api/persona/adaptation', json={'paused':'yes'})).status_code == 422
        assert (await client.put('/api/persona/adaptation', json={'paused':True})).json()['paused']
        assert (await client.post('/api/persona/adaptation/missing/undo')).status_code == 404
        assert (await client.post('/api/persona/adaptation/reset')).status_code == 200
    assert pa.snapshot()['paused']

@pytest.mark.anyio
async def test_undo_restores_update_and_is_idempotent():
    first = await learn()
    assert (await learn('2', behavior='先用一句话概括结论'))['status'] == 'applied'
    pa.undo(first['rule_id'])
    state = pa.snapshot()
    assert state['rules'][0]['behavior'] == '先说明结论'
    assert state['rules'][0]['enabled']
    pa.undo(first['rule_id'])
    assert pa.snapshot()['version'] == state['version']


@pytest.mark.anyio
async def test_total_rule_budget_and_retrieval_limit(monkeypatch):
    monkeypatch.setattr(pa, 'MAX_DAILY_UPDATES', 30)
    for index in range(pa.MAX_RULES):
        assert (await learn(str(index), scene=f'独立场景{chr(0x4e00+index)} {chr(97+index)*12}'))['status'] == 'applied'
    assert (await learn('overflow', scene='另一个场景'))['status'] == 'budget'
    prompt = pa.adaptation_prompt('独立场景')
    assert prompt.count('"scene"') == 3
    assert len(prompt) < pa.MAX_PROMPT_CHARACTERS + 300


@pytest.mark.anyio
async def test_failed_query_is_not_reprocessed():
    failing = AsyncMock(side_effect=RuntimeError('provider down'))
    assert (await pa.adapt_turn('s','t','用户消息',failing))['status'] == 'failed'
    assert (await pa.adapt_turn('s','t','用户消息',failing))['status'] == 'already_processed'
    assert failing.await_count == 1


def test_corrupt_adaptation_is_preserved():
    pa._path().write_bytes(b'not sqlite')
    import sqlite3
    with pytest.raises(sqlite3.DatabaseError):
        pa.snapshot()
    assert pa._path().read_bytes() == b'not sqlite'
