"""Real Chromium + isolated production HTTP API; no external model calls.

Run from frontend: npm run test:e2e. --url checks an existing frontend with
--api-url pointing to its isolated fixture API; default starts both processes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / 'frontend'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_url(url, proc):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'server exited: {proc.returncode}')
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    raise RuntimeError(f'server startup timed out: {url}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / '.scratch/frontend-browser')
    parser.add_argument('--url', help='Existing isolated frontend connected to the scripted fixture')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='mellowday-vue-'))
    api_port, web_port = free_port(), free_port()
    api = f'http://127.0.0.1:{api_port}'
    url = f'http://127.0.0.1:{web_port}'
    if args.url:
        url = api = args.url.rstrip('/')
    env = os.environ.copy()
    env.update(MELLOWDAY_DEV_API_URL=api, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    procs = []
    logs = []
    checks = []
    page_errors = []
    result = {'data_dir': str(data), 'url': url, 'mode': 'scripted-agent-real-http', 'checks': checks}

    def passed(name):
        checks.append(name)
        print(f'PASS {name}', flush=True)

    try:
        for name, command, cwd in ([] if args.url else [
            ('api', [sys.executable, str(Path(__file__).with_name('fixture_server.py')), '--data', str(data), '--port', str(api_port)], ROOT),
            ('web', ['node', str(FRONTEND / 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], FRONTEND),
        ]):
            log = (args.output / f'{name}.log').open('w', encoding='utf-8'); logs.append(log)
            procs.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT))
        if procs:
            wait_url(api + '/api/health', procs[0]); wait_url(url, procs[1])
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, timezone_id='Asia/Shanghai', reduced_motion='reduce')
            page.on('pageerror', lambda e: page_errors.append(str(e)))
            page.goto(url); page.wait_for_load_state('networkidle')
            (args.output / 'initial-dom.html').write_text(page.content(), encoding='utf-8')
            expect(page.get_by_role('heading', name='与 MellowDay 聊聊')).to_be_visible()
            page.screenshot(path=str(args.output / 'sky-desktop.png'), full_page=True)
            passed('Vue shell and default theme render')
            expect(page.locator('.primary-nav').get_by_role('link')).to_have_count(2)
            expect(page.locator('.primary-nav').get_by_role('link', name='对话', exact=True)).to_be_visible()
            expect(page.locator('.primary-nav').get_by_role('link', name='设置', exact=True)).to_be_visible()
            expect(page.locator('.secondary-nav')).to_have_count(0)
            page.get_by_role('link', name='设置', exact=True).click()
            for label in ['人格', '记忆', '已学会的方法', '任务', '笔记']:
                expect(page.locator('.secondary-nav').get_by_role('link', name=label, exact=True)).to_be_visible()
            page.get_by_label('称呼', exact=True).fill('浏览器小悠')
            page.get_by_label('说话示例', exact=True).fill('今天辛苦啦，想先聊一会儿吗？')
            page.get_by_role('button', name='保存人格', exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('人格已保存')
            page.reload(); page.wait_for_load_state('networkidle')
            expect(page.get_by_label('称呼', exact=True)).to_have_value('浏览器小悠')
            expect(page.get_by_label('说话示例', exact=True)).to_have_value('今天辛苦啦，想先聊一会儿吗？')
            page.get_by_role('button', name='暂停演化', exact=True).click()
            expect(page.get_by_role('button', name='恢复演化', exact=True)).to_be_visible()
            page.get_by_role('button', name='恢复演化', exact=True).click()
            expect(page.get_by_role('button', name='暂停演化', exact=True)).to_be_visible()
            page.get_by_label('称呼', exact=True).fill('失败保留草稿')
            def persona_failure(route):
                if route.request.method == 'PUT':
                    route.fulfill(status=503, content_type='application/json', body='{"detail":"隔离验收写入失败"}')
                else:
                    route.continue_()
            page.route('**/api/persona', persona_failure)
            page.get_by_role('button', name='保存人格', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('隔离验收写入失败')
            expect(page.get_by_label('称呼', exact=True)).to_have_value('失败保留草稿')
            page.unroute('**/api/persona', persona_failure)
            assert httpx.get(api + '/api/persona').json()['name'] == '浏览器小悠'
            passed('chat-first navigation and settings; persona examples persist; adaptation pause/resume; failed save retains draft')
            page.get_by_role('link', name='对话', exact=True).click()
            page.get_by_role('textbox', name='想说的话').fill('确认学习')
            page.get_by_role('button', name='发送', exact=True).click()
            expect(page.get_by_role('button', name='同意本次操作')).to_be_visible(timeout=15000)
            expect(page.get_by_role('button', name='新对话', exact=True)).to_be_disabled()
            page.get_by_role('link', name='设置', exact=True).click()
            expect(page.get_by_text('有一项操作等待你的确认', exact=False)).to_be_visible()
            page.get_by_text('有一项操作等待你的确认', exact=False).click()
            page.get_by_role('button', name='同意本次操作').click()
            expect(page.get_by_role('button', name='停止', exact=True)).to_have_count(0, timeout=15000)
            notes = httpx.get(api + '/api/records/notes').json()['records']
            assert len([r for r in notes if r['title'] == '确认回执']) == 1
            passed('confirmation after turn_end survives navigation and executes once')
            page.get_by_role('textbox', name='想说的话').fill('工具原文'); page.get_by_role('button', name='发送', exact=True).click()
            expect(page.get_by_role('button', name='停止', exact=True)).to_have_count(0, timeout=15000)
            page.goto(url + '/#/settings/history'); page.wait_for_load_state('networkidle')
            page.locator('.history-list .session-item').first.click()
            page.get_by_role('button', name='原始执行过程').click()
            page.locator('details.trace-row summary').filter(has_text='工具结果').click()
            page.get_by_role('button', name='查看完整原文').click()
            expect(page.locator('.original-text')).to_contain_text('第0000条')
            for _ in range(12):
                more = page.get_by_role('button', name='继续加载')
                if not more.count(): break
                more.click(); page.wait_for_timeout(100)
                page.wait_for_timeout(100)
            from fixture_server import LONG_TEXT
            assert page.locator('.original-text').inner_text() == LONG_TEXT
            page.get_by_role('searchbox', name='在原文中查找').fill('原文结束标记'); page.get_by_role('button', name='查找', exact=True).click()
            expect(page.locator('.original-text')).to_contain_text('原文结束标记')
            page.get_by_role('button', name='从头查看').click(); expect(page.locator('.original-text')).to_contain_text('第0000条')
            page.get_by_role('button', name='收起原文').click(); page.get_by_role('button', name='查看完整原文').click(); expect(page.locator('.original-text')).to_contain_text('第0000条')
            passed('history and complete artifact pagination/search/reopen')
            page.goto(url + '/#/life/tasks'); page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='新建任务').click(); page.get_by_role('textbox', name='标题', exact=True).fill('浏览器验收任务')
            page.get_by_role('textbox', name='内容', exact=True).fill('完整的中文内容')
            page.get_by_role('button', name='保存', exact=True).click(); expect(page.get_by_role('heading', name='浏览器验收任务')).to_be_visible()
            card = page.locator('.record-card').filter(has=page.get_by_role('heading', name='浏览器验收任务'))
            card.get_by_role('button', name='编辑', exact=True).click(); page.get_by_role('textbox', name='内容', exact=True).fill('修改后的内容'); page.get_by_role('button', name='保存', exact=True).click()
            expect(card).to_contain_text('修改后的内容')
            page.get_by_role('button', name='撤销上一步').click(); expect(card).to_contain_text('完整的中文内容')
            card.get_by_role('button', name='完成', exact=True).click(); expect(card.get_by_text('已完成', exact=True)).to_be_visible()
            card.get_by_role('button', name='恢复', exact=True).click(); expect(card.get_by_text('待完成', exact=True)).to_be_visible()
            passed('records create/edit/undo/complete/reopen over real API')
            from current_calendar import verify_calendar
            verify_calendar(page, api, url, passed, args.output)

            page.goto(url + '/#/settings/skills'); page.wait_for_load_state('networkidle'); page.locator('.skill-item').filter(has_text='每日整理').click()
            page.get_by_role('button', name='编辑规则').click(); page.get_by_role('textbox', name='规则正文').fill('先看日历，再处理三件最重要的事。'); page.get_by_role('button', name='保存规则').click()
            expect(page.locator('.skill-body').first).to_contain_text('先看日历，再处理三件最重要的事。')
            page.get_by_role('button', name='停用', exact=True).click(); expect(page.get_by_role('button', name='编辑规则')).to_be_disabled()
            page.get_by_role('button', name='启用', exact=True).click(); expect(page.get_by_role('button', name='编辑规则')).to_be_enabled()
            passed('skill edit and enable/disable')
            page.locator('.version-list button').last.click()
            page.get_by_role('button',name='恢复此版本',exact=True).click()
            page.get_by_role('button',name='确认恢复',exact=True).click()
            expect(page.locator('.skill-body').first).to_contain_text('先列固定安排')
            passed('skill whole-version restore')
            page.goto(url + '/#/settings/providers'); page.wait_for_load_state('networkidle')
            expect(page.get_by_label('API Key（留空保留现有值）')).to_have_value('')
            page.get_by_role('textbox', name='模型名称').fill('ignored-by-env'); page.get_by_role('button', name='保存配置').click()
            expect(page.get_by_role('textbox', name='模型名称')).to_have_value('fixture')
            assert 'fixture-only' not in page.content()
            passed('model config reflects environment override without revealing credential')
            page.goto(url + '/#/settings/appearance'); page.wait_for_load_state('networkidle')
            for label, key in [('晴空','sky'),('樱粉','sakura'),('薄荷','mint'),('夜色','night'),('简约','minimal')]:
                page.locator('.theme-choice').filter(has_text=label).click(); expect(page.locator('html')).to_have_attribute('data-theme', key)
            page.reload(); expect(page.locator('html')).to_have_attribute('data-theme','minimal')
            page.locator('.theme-choice').filter(has_text='夜色').click(); page.screenshot(path=str(args.output / 'night-desktop.png'),full_page=True)
            for width in [390,768,1440]:
                page.set_viewport_size({'width':width,'height':900}); page.goto(url+'/#/life/tasks'); page.wait_for_load_state('networkidle')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(args.output / f'records-{width}.png'),full_page=True)
                if width==390:
                    page.get_by_role('button',name='打开导航').click(); expect(page.get_by_role('dialog',name='主导航')).to_be_visible(); page.keyboard.press('Escape'); expect(page.get_by_role('button',name='打开导航')).to_be_focused()
            passed('five themes persist; responsive layouts and drawer focus')
            assert not page_errors,page_errors
            passed('no browser exceptions')
            browser.close()
        result['ok']=True
    except Exception as exc:
        try:
            page.screenshot(path=str(args.output/'failure.png'),full_page=True)
            (args.output/'failure-dom.html').write_text(page.content(),encoding='utf-8')
        except Exception:
            pass
        result.update(ok=False,error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        result['page_errors']=page_errors
        (args.output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        for proc in reversed(procs):
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill()
        for log in logs:log.close()


if __name__=='__main__':main()
