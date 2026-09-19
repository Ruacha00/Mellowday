import json
import asyncio
from unittest.mock import AsyncMock

import pytest

from mellowday.personal_assistant.skill_consent import explicitly_authorized
from mellowday.runtime.agent import Agent
from mellowday.runtime.skills.online_skill_evolution import SkillWriteSummary
from mellowday.web_app.app import create_app
from mellowday.web_app.service import SessionRegistry


@pytest.mark.anyio
async def test_product_rejects_forged_runtime_tools():
    agent = Agent(api_key='test', api_base='http://127.0.0.1:9/v1',
                  product_mode=True, custom_tools=[])
    for name in ['agent', 'skill', 'skill_create', 'enter_plan_mode', 'exit_plan_mode', 'mcp__anything']:
        result = json.loads(await agent._execute_tool_call(name, {}))
        assert result['error'] == 'tool_not_available'
    previous = agent.permission_mode
    assert agent.toggle_plan_mode() == previous


@pytest.mark.anyio
async def test_skill_authorization_sees_full_tail_and_rejects_preview_only():
    messages = [{'role': 'user', 'content': '以后整理日程先按时间排序'}]
    change = {'candidate': {'instructions': '按时间排序' * 100 + 'UNAUTHORIZED_TAIL'}}
    summary = SkillWriteSummary('truncated preview', change)
    seen = []

    async def query(system, payload):
        seen.append(json.loads(payload))
        return '{"authorized":false,"evidence":"以后整理日程先按时间排序"}'

    assert not await explicitly_authorized(messages, summary, query)
    assert seen[0]['proposed_change'] == change
    query_mock = AsyncMock()
    assert not await explicitly_authorized(messages, str(summary), query_mock)
    query_mock.assert_not_called()


@pytest.mark.anyio
async def test_application_owns_scheduler_lifecycle():
    registry = SessionRegistry()
    app = create_app(store=registry.store, registry=registry)
    async with app.router.lifespan_context(app):
        task = registry.schedule._task
        assert task is not None and not task.done()
    assert task.done()


def test_report_history_is_not_limited_by_notification_inbox():
    registry = SessionRegistry()
    registry.get('report-history')
    with registry.store._connect() as db:
        for index in range(505):
            payload = dict(id=str(index), kind='report', session_id='report-history',
                           body=f'report {index}', created_at='2026-09-19T08:00:00+00:00')
            db.execute('INSERT INTO schedule_notifications VALUES (?,?,0,1)',
                       (str(index), json.dumps(payload)))
    detail = registry.session_detail('report-history')
    assert len(detail['messages']) == 505
    assert len(detail['trace_display']) == 505
    assert detail['trace'][0]['time'] == '2026-09-19T08:00:00+00:00'
    registry.drop('report-history')
    assert not registry.session_detail('report-history')['messages']


@pytest.mark.anyio
@pytest.mark.parametrize('phase', ['extract', 'confirm'])
async def test_abort_stops_post_reply_memory_and_persona(monkeypatch, phase):
    from httpx import AsyncClient, ASGITransport
    from mellowday.personal_assistant import persona_adaptation
    entered = asyncio.Event()
    adapt = AsyncMock()
    monkeypatch.setattr(persona_adaptation, 'adapt_turn', adapt)

    class AgentStub:
        _aborted = False

        def set_confirm_fn(self, fn):
            self.confirm = fn

        def abort(self):
            self._aborted = True

        async def chat(self, message):
            pass

        def _build_side_query(self, **kwargs):
            async def query(system, payload):
                if phase == 'extract':
                    entered.set()
                    await asyncio.Event().wait()
                return json.dumps({'candidate': dict(content='我长期吃素', label='饮食',
                    kind='preference', evidence='我长期吃素', explicit=False)})
            return query

    registry = SessionRegistry(agent_factory=lambda **kwargs: AgentStub())
    monkeypatch.setattr(registry, '_adopt_model_config', lambda state: None)
    app = create_app(store=registry.store, registry=registry)

    async def consume():
        result = []
        async for event in registry.run_turn('stop-learning', '我长期吃素'):
            result.append(event)
            if event['type'] == 'confirmation':
                entered.set()
        return result

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 3)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/api/chat/stop-learning/abort')).status_code == 200
    result = await asyncio.wait_for(task, 3)
    assert result[-1]['type'] == 'done'
    assert registry.store.list_records('memories') == []
    adapt.assert_not_called()


def test_default_calendar_skill_respects_disable():
    from mellowday.personal_assistant.default_skills import install_calendar_method
    from mellowday.runtime.skills import disable_skill, discover_skills
    install_calendar_method()
    assert any(s.name == 'calendar-conversation' for s in discover_skills())
    assert disable_skill('calendar-conversation')['ok']
    install_calendar_method()
    assert not any(s.name == 'calendar-conversation' for s in discover_skills())
