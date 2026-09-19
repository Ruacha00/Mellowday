"""Additional browser checks; use only an isolated scripted fixture deployment."""
import argparse
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
url = args.url.rstrip('/')
checks = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.goto(url + '/#/settings/providers')
    limit = page.get_by_role('spinbutton', name='最大工具轮次')
    limit.fill('7')
    with page.expect_response('**/api/config'):
        page.get_by_role('button', name='保存配置').click()
    expect(limit).to_be_enabled()
    assert httpx.get(url + '/api/config').json()['max_turns'] == 7
    limit.fill('')
    with page.expect_response('**/api/config'):
        page.get_by_role('button', name='保存配置').click()
    page.reload()
    expect(limit).to_have_value('')
    assert httpx.get(url + '/api/config').json()['max_turns'] is None
    checks.append('saved max_turns can be cleared and survives reload')
    page.goto(url + '/#/conversation')
    page.get_by_role('button', name='新对话', exact=True).click()
    draft = page.get_by_role('textbox', name='想说的话')
    draft.fill('慢速')
    page.get_by_role('button', name='发送', exact=True).click()
    expect(page.get_by_text('已经收到你的想法。', exact=False)).to_be_visible()
    page.get_by_role('button', name='停止', exact=True).click()
    expect(page.get_by_role('button', name='停止', exact=True)).to_have_count(0)
    draft.fill('继续')
    page.get_by_role('button', name='发送', exact=True).click()
    expect(page.get_by_role('button', name='停止', exact=True)).to_have_count(0, timeout=15000)
    expect(page.get_by_text('继续', exact=True)).to_be_visible()
    checks.append('browser stop releases current turn and next turn completes')
    draft.fill('错误')
    page.get_by_role('button', name='发送', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('可见的测试错误')
    expect(draft).to_have_value('错误')
    checks.append('runtime error is visible and failed draft is retained')
    page.goto(url + '/#/today')
    expect(page.get_by_role('heading', name='与 MellowDay 聊聊', exact=True)).to_be_visible()
    expect(page.get_by_role('alert')).to_have_count(0)
    checks.append('legacy today route redirects to conversation through production proxy')
    browser.close()
result = {'ok': True, 'checks': checks}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
