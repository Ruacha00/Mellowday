"""Isolated real HTTP fixture. Scripted agent, production API/store/session layer."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
LONG_TEXT = ''.join(f'第{i:04d}条：保留完整中文工具结果。\n' for i in range(650)) + '原文结束标记'


def create_fixture(data: Path):
    os.environ.update(MELLOWDAY_DATA_DIR=str(data), MELLOWDAY_ENV_FILE='', MELLOWDAY_API_KEY='fixture-only', MELLOWDAY_API_BASE='http://127.0.0.1:1', MELLOWDAY_MODEL='fixture')
    from mellowday.runtime import events, sessions
    from mellowday.runtime.skills import create_skill_file
    from mellowday.storage.store import Store
    from mellowday.web_app.app import create_app
    from mellowday.web_app.service import SessionRegistry
    data.mkdir(parents=True, exist_ok=True)
    create_skill_file(name='每日整理', description='整理当天的生活安排', when_to_use='整理今天时', instructions='# 规则\n先列固定安排，再列三件重要的事。')
    store = Store(data_dir=data)

    class Agent:
        def __init__(self, session_id):
            self.session_id = session_id
            self.messages = []
            self.confirm_fn = None
            self.aborted = False

        def set_confirm_fn(self, fn):
            self.confirm_fn = fn

        def abort(self):
            self.aborted = True

        async def chat(self, message):
            self.aborted = False
            events.emit({'type': 'text_delta', 'text': '已经收到你的想法。'})
            if message == '慢速':
                for _ in range(120):
                    if self.aborted:
                        return
                    await asyncio.sleep(.1)
                    events.emit({'type': 'text_delta', 'text': '慢慢来。'})
                return
            if message == '长等待':
                await asyncio.sleep(65)
                events.emit({'type': 'text_delta', 'text': '等待后仍然连通。'})
            if message == '工具原文':
                events.emit({'type': 'tool_start', 'name': 'list_notes', 'arguments': {'limit': 650}})
                artifact = sessions.save_tool_artifact(self.session_id, 'list_notes', LONG_TEXT)
                events.emit({'type': 'tool_result', 'name': 'list_notes', 'result': '完整结果已保存', 'ref': artifact['ref'], 'chars': artifact['chars'], 'preview': artifact['preview'], 'truncated': True})
            events.emit({'type': 'turn_end'})
            if message == '确认学习':
                events.emit({'type': 'skill_candidate_proposed', 'skill': '每日整理', 'action': 'evolve'})
                approved = await self.confirm_fn('保存长期规则：先列三件重要的事')
                if approved:
                    store.create_record('notes', {'title': '确认回执', 'detail': '只执行一次'})
                events.emit({'type': 'skill_candidate_applied' if approved else 'skill_write_denied', 'skill': '每日整理', 'reason': '' if approved else 'user_denied'})
            elif message == '错误':
                raise RuntimeError('可见的测试错误')
            else:
                events.emit({'type': 'skill_candidate_skipped', 'reason': 'no_window'})

    registry = SessionRegistry(store=store, agent_factory=lambda session_id, **kwargs: Agent(session_id))
    return create_app(store=store, registry=registry)


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    uvicorn.run(create_fixture(args.data), host=args.host, port=args.port, log_level='warning')
