"""Install the editable calendar conversation method once per data directory."""
from mellowday import paths
from mellowday.runtime.skills import create_skill


def install_calendar_method() -> None:
    marker = paths.data_dir() / '.calendar-method-installed'
    if marker.exists():
        return
    name = 'calendar-conversation'
    target = paths.skills_dir() / name / 'SKILL.md'
    if not target.exists():
        result = create_skill(
            name=name,
            description='通过聊天查询、解释日程安排和提醒，不使用独立今日概览。',
            when_to_use='用户询问今天、明天、本周、下周的日程安排、会议或空闲时间。',
            instructions=(
                '先根据用户时区确定起止日期；不明确的日期先询问。使用 calendar_events 查询完整时间区间，'
                '按时间顺序说明标题、开始与结束时间，明确标注全天事项。没有安排时如实告知。'
                '用户要查看日历时使用 calendar_open。只读询问不得新建、更改日程或订阅。'
                '只有用户明确提出时才建立提醒或定时汇报；确认时间、时区、频率与接收会话。'
                '当前定时汇报内容是投递当天日程，周频率不表示整周汇总。'
                '用户要求未来长期采用新的整理方法时，学习流程可以更新本技能；不改变权限或核心人格。'
            ), actor='system', tags=['日程', '日历', '安排', '提醒'],
        )
        if not result.get('ok'):
            raise RuntimeError('Could not install calendar conversation method')
    marker.touch()
