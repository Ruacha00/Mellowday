"""Motion/accessibility/performance checks against an isolated scripted fixture."""
import argparse
import json
import math
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True, help='Isolated scripted fixture, never daily data')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--cpu-rate', type=int, default=4)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
report = {'ok': False, 'cpu_throttle': args.cpu_rate, 'checks': []}

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='no-preference')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(args.url)
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='与 MellowDay 聊聊')).to_be_visible()
        assert page.locator('.route-page').evaluate("el => getComputedStyle(el).animationName") == 'page-arrive'
        page.wait_for_timeout(350)
        assert page.evaluate('document.getAnimations().length') == 0
        report['checks'].append('finite page entry; no idle animations')

        cdp = page.context.new_cdp_session(page)
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': args.cpu_rate})
        page.evaluate('''() => {
          window.motionQA = {frames: [], tasks: [], running: true};
          window.motionObserver = new PerformanceObserver(list => {
            for (const entry of list.getEntries()) motionQA.tasks.push(entry.duration);
          });
          motionObserver.observe({type: 'longtask'});
          let last = performance.now();
          function frame(now) {
            motionQA.frames.push(now - last); last = now;
            if (motionQA.running) requestAnimationFrame(frame);
          }
          requestAnimationFrame(frame);
        }''')
        for name in ['今日', '生活', '记忆', '设置', '对话'] * 2:
            page.get_by_role('link', name=name, exact=True).click()
            page.wait_for_timeout(280)
            expect(page.locator('.route-page')).to_have_count(1)
        draft = page.get_by_role('textbox', name='想说的话')
        draft.fill('慢速')
        page.get_by_role('button', name='发送', exact=True).click()
        expect(page.locator('.thinking-dots')).to_be_visible()
        page.wait_for_timeout(1000)
        names = page.evaluate('document.getAnimations().map(a => a.animationName)')
        assert names == ['thinking-breathe'] * 3, names
        page.get_by_role('button', name='停止', exact=True).click()
        expect(page.locator('.thinking-dots')).to_have_count(0)
        page.wait_for_timeout(350)
        assert page.evaluate('document.getAnimations().length') == 0
        samples = page.evaluate('''() => {
          motionQA.running = false; motionObserver.disconnect(); return motionQA;
        }''')
        frames = sorted(samples['frames'][1:])
        report['performance'] = {
            'frames': len(frames),
            'frame_p95_ms': round(frames[math.ceil(len(frames) * .95) - 1], 2),
            'frames_over_50ms': sum(f > 50 for f in frames),
            'long_tasks': len(samples['tasks']),
            'longest_task_ms': round(max(samples['tasks'], default=0), 2),
        }
        assert report['performance']['frame_p95_ms'] <= 50, report['performance']
        report['checks'].append('4x CPU navigation and streaming: p95 frame interval <= 50ms; only three active reply dots')
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': 1})

        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.locator('.sidebar')).to_have_attribute('inert', '')
        page.get_by_role('button', name='打开导航').click()
        expect(page.get_by_role('dialog', name='主导航')).to_be_visible()
        page.screenshot(path=str(args.output / 'mobile-drawer.png'))
        page.keyboard.press('Escape')
        expect(page.locator('.sidebar')).to_have_attribute('inert', '')
        expect(page.get_by_role('button', name='打开导航')).to_be_focused()
        page.wait_for_timeout(300)
        expect(page.locator('.sidebar')).not_to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button', name='打开导航').click()
        page.set_viewport_size({'width': 1440, 'height': 1000})
        expect(page.get_by_role('dialog', name='主导航')).to_have_count(0)
        expect(page.locator('.workspace')).not_to_have_attribute('inert', '')
        report['checks'].append('mobile drawer enters/exits, restores focus, stays inert when closed; resize releases workspace')

        draft.fill('慢速')
        page.get_by_role('button', name='发送', exact=True).click()
        expect(page.locator('.thinking-dots')).to_be_visible()
        page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true, value:true}); document.dispatchEvent(new Event('visibilitychange'))")
        assert page.locator('.thinking-dots i').first.evaluate("el => getComputedStyle(el).animationPlayState") == 'paused'
        page.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange'))")
        report['checks'].append('simulated visibility event pauses indicator')
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.thinking-dots i').first.evaluate("el => getComputedStyle(el).animationName") == 'none'
        page.get_by_role('button', name='停止', exact=True).click()
        page.get_by_role('link', name='今日', exact=True).click()
        assert page.locator('.route-page').evaluate("el => getComputedStyle(el).animationName") == 'none'
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('.sidebar').evaluate("el => getComputedStyle(el).transitionDuration") == '0s'
        page.get_by_role('button', name='打开导航').click()
        expect(page.get_by_role('dialog', name='主导航')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('button', name='打开导航')).to_be_focused()
        assert page.evaluate('document.getAnimations().length') == 0
        report['checks'].append('reduced motion disables page/drawer/indicator motion while controls remain usable')
        assert not errors, errors
        report['ok'] = True
    finally:
        report['page_errors'] = errors
        if not report['ok']:
            page.screenshot(path=str(args.output / 'failure.png'))
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        browser.close()
print(json.dumps(report, ensure_ascii=False, indent=2))
