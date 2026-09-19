"""Exercise persona learning through SessionRegistry and real Agent request boundary."""
import json
from unittest.mock import AsyncMock

import pytest

from mellowday.personal_assistant import persona_adaptation as pa
from mellowday.runtime.agent import Agent
from mellowday.runtime import events
from mellowday.web_app.service import SessionRegistry


@pytest.mark.anyio
async def test_registry_learns_then_next_real_agent_request_adopts_rules(monkeypatch):
    captured = []
    query_inputs = []

    async def side_query(system, message):
        query_inputs.append((system, json.loads(message)))
        if 'ONE worthwhile personal memory' in system:
            return '{"candidate":null}'
        if 'Extract at most ONE durable expression adaptation' in system:
            user_text = json.loads(message)['user_message']
            if '以后' not in user_text:
                return '{"candidate":null}'
            return json.dumps({'candidate': {
                'scene': '讨论技术问题', 'behavior': '先说结论再解释', 'example': '',
                'quote': user_text, 'explicit': True}}, ensure_ascii=False)
        if 'Review a proposed small expression adjustment' in system:
            return '{"allowed":true}'
        raise AssertionError(system)

    def factory(session_id, store, tool_executor):
        agent = Agent(api_base='http://127.0.0.1:9/v1', api_key='test',
                      product_mode=True, custom_tools=[], tool_executor=tool_executor)
        agent.session_id = session_id
        monkeypatch.setattr(agent, '_build_side_query', lambda **_: side_query)
        monkeypatch.setattr(agent, '_run_skill_usage_tracking', AsyncMock())
        monkeypatch.setattr(agent, '_run_online_skill_evolution', AsyncMock())
        monkeypatch.setattr(agent, '_augment_user_message_with_skill_context', lambda message: (message, None))

        async def model_reply(**kwargs):
            captured.append(agent._openai_messages[0]['content'])
            events.emit({'type': 'text_delta', 'text': '好的。'})
            return {'choices': [{'message': {'role': 'assistant', 'content': '好的。'}}]}
        monkeypatch.setattr(agent, '_call_openai_stream', model_reply)
        return agent

    registry = SessionRegistry(agent_factory=factory)
    monkeypatch.setattr(registry, '_adopt_model_config', lambda state: None)
    first = [event async for event in registry.run_turn('persona-real', '以后讨论技术问题先说结论再解释')]
    assert first[-1]['type'] == 'done'
    assert not any(event['type'] == 'error' for event in first), first
    assert 'User-adapted expression rules' not in captured[0]
    rule = pa.snapshot()['rules'][0]
    assert rule['source'][0]['session_id'] == 'persona-real'
    assert rule['source'][0]['turn_id'] == '1'

    second = [event async for event in registry.run_turn('persona-real', '继续讨论技术问题')]
    assert second[-1]['type'] == 'done'
    assert '先说结论再解释' in captured[1]
    assert 'User-adapted expression rules' in captured[1]
    assert len(registry.history('persona-real')) == 4
    assert not any(event['type'] == 'confirmation' for event in first + second)
    # Evaluator receives current input only, not the previous assistant reply.
    adaptation_inputs = [value for system, value in query_inputs if system.startswith('Extract at most ONE')]
    assert adaptation_inputs[1]['user_message'] == '继续讨论技术问题'
    assert set(adaptation_inputs[1]) == {'core', 'user_message'}

    pa.undo(rule['id'])
    [event async for event in registry.run_turn('persona-real', '继续讨论技术问题')]
    assert 'User-adapted expression rules' not in captured[2]
