"""Calendar UI acceptance against isolated real API and production scheduler."""
from datetime import datetime, timedelta, timezone
import time
import httpx
from playwright.sync_api import expect


def verify_calendar(page, api, url, passed, output):
    page.goto(url + '/#/conversation'); page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='日历', exact=True).click()
    drawer = page.get_by_role('complementary', name='日历侧栏')
    expect(drawer).to_be_visible()
    assert '/conversation' in page.url
    drawer.get_by_role('button', name='＋ 新建日程', exact=True).click()
    drawer.get_by_label('标题', exact=True).fill('浏览器日历事项')
    drawer.get_by_label('备注', exact=True).fill('有开始结束区间')
    drawer.get_by_label('提醒', exact=False).select_option(label='不提醒')
    drawer.get_by_role('button', name='保存', exact=True).click()
    event = drawer.locator('.fc-event').filter(has_text='浏览器日历事项')
    expect(event).to_be_visible()
    event.click()
    drawer.get_by_label('标题', exact=True).fill('已修改日历事项')
    drawer.get_by_role('button', name='保存', exact=True).click()
    event = drawer.locator('.fc-event').filter(has_text='已修改日历事项')
    expect(event).to_be_visible()
    page.screenshot(path=str(output/'calendar-desktop.png'),full_page=True)
    event.click(); drawer.get_by_role('button', name='删除', exact=True).click()
    drawer.get_by_role('button', name='确认删除', exact=True).click()
    expect(event).to_have_count(0)
    passed('calendar drawer creates edits and deletes interval events without leaving chat')
    drawer.get_by_role('button', name='定时汇报', exact=True).click()
    drawer.get_by_role('button', name='＋ 新建汇报', exact=True).click()
    drawer.get_by_label('汇报名称', exact=True).fill('浏览器汇报订阅')
    with page.expect_response('**/api/calendar/subscriptions') as saved:
        drawer.get_by_role('button', name='保存', exact=True).click()
    assert saved.value.ok, saved.value.text()
    subscription = drawer.locator('.subscription-link').filter(has_text='浏览器汇报订阅')
    expect(subscription).to_be_visible()
    subscription.click(); drawer.get_by_label('启用订阅', exact=True).uncheck()
    drawer.get_by_role('button', name='保存', exact=True).click()
    expect(subscription).to_contain_text('已暂停')
    subscription.click(); drawer.get_by_role('button', name='删除订阅', exact=True).click()
    drawer.get_by_role('button', name='确认删除', exact=True).click()
    expect(subscription).to_have_count(0)
    passed('scheduled report subscription create pause and delete through UI')
    drawer.get_by_role('button', name='关闭日历', exact=True).click()
    now = datetime.now(timezone.utc)
    response = httpx.post(api+'/api/calendar/events',json={
        'title':'浏览器到时提醒','detail':'真实调度消息','start_at':(now-timedelta(seconds=1)).isoformat(),
        'end_at':(now+timedelta(hours=1)).isoformat(),'timezone':'Asia/Shanghai',
        'all_day':False,'recurrence':'none','reminder_minutes':0})
    response.raise_for_status()
    event_id=response.json()['event']['id']
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        notices=httpx.get(api+'/api/calendar/notifications').json()['notifications']
        matching=[n for n in notices if n.get('event_id')==event_id]
        if matching:break
        time.sleep(.25)
    assert matching, 'real scheduler failed to produce reminder'
    page.reload(); page.wait_for_load_state('networkidle')
    bubble=page.locator('.notification-bubble').filter(has_text='浏览器到时提醒')
    expect(bubble).to_be_visible()
    bubble.locator('.notification-body').click()
    expect(drawer.get_by_label('标题', exact=True)).to_have_value('浏览器到时提醒')
    expect(bubble).to_have_count(0)
    assert next(n for n in httpx.get(api+'/api/calendar/notifications').json()['notifications'] if n['id']==matching[0]['id'])['read']
    page.set_viewport_size({'width':390,'height':900})
    expect(drawer).to_have_css('width', '390px')
    page.wait_for_function('''() => { const d=document.querySelector('.calendar-drawer'); const cells=d.querySelectorAll('.fc-col-header-cell'); return cells.length === 7 && cells[6].getBoundingClientRect().right <= d.getBoundingClientRect().right; }''')
    assert drawer.evaluate('(el) => el.scrollWidth <= el.clientWidth'), 'calendar drawer has internal horizontal overflow'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(output/'calendar-mobile.png'),full_page=True)
    drawer.get_by_role('button',name='关闭日历',exact=True).click()
    page.set_viewport_size({'width':1440,'height':1000})
    passed('real scheduler reminder bubble opens event and persists read state; mobile calendar fits')
