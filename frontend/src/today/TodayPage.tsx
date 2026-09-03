import { useEffect, useRef, useState } from "react";

import { LatestRequest } from "../services/requestLifecycle";
import type {
  DailyReview,
  DailyReviewCalendarEvent,
  DailyReviewService,
  DailyReviewTask,
} from "../services/dailyReviewApi";
import type { TaskService } from "../services/taskApi";

export type TodayLoadState = "loading" | "ready" | "error";

export interface TodayPageSnapshot {
  review: DailyReview | null;
  loadState: TodayLoadState;
  refreshing: boolean;
  busyTaskId: string | null;
  notice: string;
}

interface TodayPageProps {
  reviewService: DailyReviewService;
  taskService: TaskService;
}

interface TodayPageViewProps {
  snapshot: TodayPageSnapshot;
  onCompleteTask: (task: DailyReviewTask) => void;
  onRefresh: () => void;
}

const initialSnapshot: TodayPageSnapshot = {
  review: null,
  loadState: "loading",
  refreshing: false,
  busyTaskId: null,
  notice: "",
};

/** Coordinates route-scoped reads and bounded Task mutations outside rendering. */
export class TodayPageCoordinator {
  private readonly loadRequest = new LatestRequest();
  private mutationController: AbortController | null = null;
  private disposed = false;
  private snapshot: TodayPageSnapshot = initialSnapshot;

  constructor(
    private readonly reviewService: DailyReviewService,
    private readonly taskService: Pick<TaskService, "setCompleted">,
    private readonly publish: (snapshot: TodayPageSnapshot) => void,
  ) {}

  start(): Promise<boolean> {
    return this.refresh(true);
  }

  async refresh(showLoading = this.snapshot.review === null): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    this.update(showLoading
      ? { loadState: "loading", refreshing: false }
      : { refreshing: true });

    try {
      const result = await this.loadRequest.run((signal) =>
        this.reviewService.getDailyReview(signal),
      );
      if (result.status !== "current" || this.disposed) {
        return false;
      }
      this.update({
        review: result.value,
        loadState: "ready",
        refreshing: false,
      });
      return true;
    } catch {
      if (!this.disposed) {
        this.update({ loadState: "error", refreshing: false });
      }
      return false;
    }
  }

  async completeTask(task: DailyReviewTask): Promise<void> {
    if (this.disposed || this.snapshot.busyTaskId !== null) {
      return;
    }
    const controller = new AbortController();
    this.mutationController = controller;
    this.update({
      busyTaskId: task.id,
      notice: `正在完成“${task.title}”…`,
    });

    try {
      await this.taskService.setCompleted(task.id, true, controller.signal);
      if (this.disposed || controller.signal.aborted) {
        return;
      }
      const refreshed = await this.refresh(false);
      if (this.disposed || controller.signal.aborted) {
        return;
      }
      this.update({
        notice: refreshed
          ? `已完成“${task.title}”。`
          : `任务“${task.title}”已完成，但今日概览暂未更新。`,
      });
    } catch {
      if (!this.disposed && !controller.signal.aborted) {
        this.update({ notice: `无法完成“${task.title}”，源任务未被更改。` });
      }
    } finally {
      if (!this.disposed && this.mutationController === controller) {
        this.mutationController = null;
        this.update({ busyTaskId: null });
      }
    }
  }

  dispose(): void {
    this.disposed = true;
    this.loadRequest.cancel();
    this.mutationController?.abort();
    this.mutationController = null;
  }

  private update(patch: Partial<TodayPageSnapshot>): void {
    if (this.disposed) {
      return;
    }
    this.snapshot = { ...this.snapshot, ...patch };
    this.publish(this.snapshot);
  }
}

export function TodayPage({ reviewService, taskService }: TodayPageProps) {
  const [snapshot, setSnapshot] = useState<TodayPageSnapshot>(initialSnapshot);
  const coordinator = useRef<TodayPageCoordinator | null>(null);

  useEffect(() => {
    setSnapshot(initialSnapshot);
    const nextCoordinator = new TodayPageCoordinator(
      reviewService,
      taskService,
      setSnapshot,
    );
    coordinator.current = nextCoordinator;
    void nextCoordinator.start();
    return () => {
      nextCoordinator.dispose();
      if (coordinator.current === nextCoordinator) {
        coordinator.current = null;
      }
    };
  }, [reviewService, taskService]);

  return (
    <TodayPageView
      onCompleteTask={(task) => void coordinator.current?.completeTask(task)}
      onRefresh={() => void coordinator.current?.refresh(snapshot.review === null)}
      snapshot={snapshot}
    />
  );
}

export function TodayPageView({
  snapshot,
  onCompleteTask,
  onRefresh,
}: TodayPageViewProps) {
  const { review, loadState, refreshing, busyTaskId, notice } = snapshot;

  if (review === null && loadState === "loading") {
    return <p aria-live="polite" className="today-loading">正在加载今日概览…</p>;
  }

  if (review === null) {
    return (
      <section className="today-page today-failure" role="alert">
        <h2>今日概览暂时不可用</h2>
        <p>生活记录没有被更改。可以稍后重试。</p>
        <button onClick={onRefresh} type="button">重新加载</button>
      </section>
    );
  }

  const dueTasks = dueOrOverdueTasks(review);
  const stale = loadState === "error";
  return (
    <section
      aria-busy={refreshing}
      className="today-page"
      data-state={stale ? "stale" : "current"}
    >
      <div className="today-summary">
        <div>
          <p className="today-date">{review.date} · {review.timezone}</p>
          <h2>今日概览</h2>
          <p>内容来自当前生活记录，不会在“今日”中另存副本。</p>
        </div>
        <button disabled={refreshing} onClick={onRefresh} type="button">
          {refreshing ? "正在刷新" : "刷新概览"}
        </button>
      </div>

      {stale ? (
        <p className="today-state" role="status">
          暂时无法取得最新内容；下面显示的是上次成功加载的概览。
        </p>
      ) : null}
      {notice.length > 0 ? (
        <p aria-live="polite" className="today-notice" role="status">{notice}</p>
      ) : null}

      <div className="today-sections">
        <TodayCalendarSection events={review.calendarEvents} />
        <section aria-labelledby="today-tasks-heading" className="today-section">
          <SectionHeading
            count={dueTasks.length}
            href="#/life/tasks"
            id="today-tasks-heading"
            label="到期任务"
            linkLabel="查看全部任务"
          />
          {dueTasks.length === 0 ? (
            <p className="today-empty">没有到期或逾期任务。</p>
          ) : (
            <ul className="today-list">
              {dueTasks.map((task) => (
                <li className="today-card" data-timing={task.timing} key={task.id}>
                  <div className="today-card-heading">
                    <h3>{task.title}</h3>
                    <span>{taskTimingLabel(task.timing)}</span>
                  </div>
                  {task.details === null ? null : <p>{task.details}</p>}
                  <p className="today-card-meta">
                    截止：{task.deadline === null ? "未设置" : readableDateTime(task.deadline)}
                  </p>
                  <div className="today-card-actions">
                    <button
                      aria-label={`完成任务：${task.title}`}
                      disabled={busyTaskId !== null}
                      onClick={() => onCompleteTask(task)}
                      type="button"
                    >
                      {busyTaskId === task.id ? "正在完成" : "完成"}
                    </button>
                    <a href="#/life/tasks">在任务中编辑</a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="today-reminders-heading" className="today-section">
          <SectionHeading
            count={review.reminders.length}
            href="#/life/reminders"
            id="today-reminders-heading"
            label="相关提醒"
            linkLabel="查看全部提醒"
          />
          {review.reminders.length === 0 ? (
            <p className="today-empty">目前没有相关提醒。</p>
          ) : (
            <ul className="today-list">
              {review.reminders.map((reminder) => (
                <li className="today-card" data-timing={reminder.timing} key={reminder.id}>
                  <div className="today-card-heading">
                    <h3>{reminder.message}</h3>
                    <span>{reminderTimingLabel(reminder.timing)}</span>
                  </div>
                  <p className="today-card-meta">提醒时间：{readableDateTime(reminder.dueAt)}</p>
                  <a href="#/life/reminders">在提醒中编辑</a>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="today-review-heading" className="today-section">
          <SectionHeading
            count={review.notes.length}
            href="#/life/notes"
            id="today-review-heading"
            label="每日回顾"
            linkLabel="查看全部笔记"
          />
          {review.notes.length === 0 ? (
            <p className="today-empty">今天没有更新的笔记。</p>
          ) : (
            <ul className="today-list">
              {review.notes.map((note) => (
                <li className="today-card" key={note.id}>
                  <h3>{note.title ?? "无标题笔记"}</h3>
                  <p className="today-note-content">{note.content}</p>
                  <a href="#/life/notes">在笔记中查看</a>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
}

function TodayCalendarSection({ events }: { events: DailyReviewCalendarEvent[] }) {
  return (
    <section aria-labelledby="today-calendar-heading" className="today-section">
      <SectionHeading
        count={events.length}
        href="#/life/calendar"
        id="today-calendar-heading"
        label="今日日程"
        linkLabel="查看完整日历"
      />
      {events.length === 0 ? (
        <p className="today-empty">今天没有日历事件。</p>
      ) : (
        <ul className="today-list">
          {events.map((event) => (
            <li className="today-card" data-timing={event.timing} key={event.id}>
              <div className="today-card-heading">
                <h3>{event.title}</h3>
                <span>{calendarTimingLabel(event.timing)}</span>
              </div>
              <p className="today-card-meta">
                {readableDateTime(event.startAt)}
                {event.endAt === null ? "" : ` – ${readableDateTime(event.endAt)}`}
              </p>
              {event.details === null ? null : <p>{event.details}</p>}
              <a href="#/life/calendar">在日历中编辑</a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SectionHeading({
  count,
  href,
  id,
  label,
  linkLabel,
}: {
  count: number;
  href: string;
  id: string;
  label: string;
  linkLabel: string;
}) {
  return (
    <div className="today-section-heading">
      <h2 id={id}>{label}</h2>
      <span aria-label={`${label} ${count} 项`}>{count}</span>
      <a href={href}>{linkLabel}</a>
    </div>
  );
}

export function dueOrOverdueTasks(review: DailyReview): DailyReviewTask[] {
  return review.tasks.filter(
    (task) => task.timing === "overdue" || task.timing === "due_today",
  );
}

function readableDateTime(value: string): string {
  const [date, rest] = value.split("T", 2);
  if (rest === undefined) {
    return date;
  }
  return `${date} ${rest.slice(0, 5)}`;
}

function taskTimingLabel(timing: DailyReviewTask["timing"]): string {
  return timing === "overdue" ? "已逾期" : "今天到期";
}

function reminderTimingLabel(timing: "overdue" | "upcoming"): string {
  return timing === "overdue" ? "已到期" : "即将提醒";
}

function calendarTimingLabel(
  timing: DailyReviewCalendarEvent["timing"],
): string {
  return {
    past: "已结束",
    ongoing: "进行中",
    upcoming: "稍后",
  }[timing];
}
