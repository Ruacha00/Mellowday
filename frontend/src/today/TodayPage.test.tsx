import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { DailyReview, DailyReviewService } from "../services/dailyReviewApi";
import type { Task } from "../services/taskApi";
import {
  TodayPageCoordinator,
  TodayPageView,
  dueOrOverdueTasks,
  type TodayPageSnapshot,
} from "./TodayPage";

const review: DailyReview = {
  date: "2026-09-01",
  timezone: "Asia/Shanghai",
  generatedAt: 100,
  tasks: [
    {
      id: "overdue",
      title: "补交报告",
      details: null,
      deadline: "2026-08-31",
      timing: "overdue",
    },
    {
      id: "due-today",
      title: "今日任务",
      details: "附上图表",
      deadline: "2026-09-01",
      timing: "due_today",
    },
    {
      id: "upcoming",
      title: "周末计划",
      details: null,
      deadline: "2026-09-05",
      timing: "upcoming",
    },
    {
      id: "unscheduled",
      title: "买茶",
      details: null,
      deadline: null,
      timing: "unscheduled",
    },
  ],
  reminders: [{
    id: "reminder-1",
    message: "参加例会",
    dueAt: "2026-09-01T10:00:00+08:00",
    deliveryState: "scheduled",
    taskId: null,
    timing: "upcoming",
  }],
  calendarEvents: [{
    id: "event-1",
    title: "午餐",
    startAt: "2026-09-01T12:00:00+08:00",
    endAt: null,
    details: "楼下见",
    timing: "upcoming",
  }],
  notes: [{
    id: "note-1",
    title: "会议准备",
    content: "带上数据",
    updatedAt: 90,
    relevance: "updated_today",
  }],
};

function readySnapshot(overrides: Partial<TodayPageSnapshot> = {}): TodayPageSnapshot {
  return {
    review,
    loadState: "ready",
    refreshing: false,
    busyTaskId: null,
    notice: "",
    ...overrides,
  };
}

describe("Today view", () => {
  it("shows only due Tasks and routes full editing to each owning Life page", () => {
    const markup = renderToStaticMarkup(
      <TodayPageView
        onCompleteTask={() => undefined}
        onRefresh={() => undefined}
        snapshot={readySnapshot()}
      />,
    );

    expect(dueOrOverdueTasks(review).map((task) => task.id)).toEqual([
      "overdue",
      "due-today",
    ]);
    expect(markup).toContain("补交报告");
    expect(markup).toContain("今日任务");
    expect(markup).not.toContain("周末计划");
    expect(markup).not.toContain("买茶");
    expect(markup).toContain('aria-label="完成任务：今日任务"');
    expect(markup).toContain('href="#/life/tasks"');
    expect(markup).toContain('href="#/life/reminders"');
    expect(markup).toContain('href="#/life/calendar"');
    expect(markup).toContain('href="#/life/notes"');
    expect(markup).toContain("参加例会");
    expect(markup).toContain("午餐");
    expect(markup).toContain("带上数据");
  });

  it("keeps partial, stale, and initial failure states understandable", () => {
    const partialReview: DailyReview = {
      ...review,
      tasks: [],
      reminders: [],
      calendarEvents: [],
      notes: [],
    };
    const partial = renderToStaticMarkup(
      <TodayPageView
        onCompleteTask={() => undefined}
        onRefresh={() => undefined}
        snapshot={readySnapshot({ review: partialReview })}
      />,
    );
    const stale = renderToStaticMarkup(
      <TodayPageView
        onCompleteTask={() => undefined}
        onRefresh={() => undefined}
        snapshot={readySnapshot({ loadState: "error" })}
      />,
    );
    const failure = renderToStaticMarkup(
      <TodayPageView
        onCompleteTask={() => undefined}
        onRefresh={() => undefined}
        snapshot={readySnapshot({ review: null, loadState: "error" })}
      />,
    );

    expect(partial).toContain("今天没有日历事件。");
    expect(partial).toContain("没有到期或逾期任务。");
    expect(partial).toContain("目前没有相关提醒。");
    expect(partial).toContain("今天没有更新的笔记。");
    expect(stale).toContain('data-state="stale"');
    expect(stale).toContain("上次成功加载的概览");
    expect(failure).toContain('role="alert"');
    expect(failure).toContain("生活记录没有被更改");
  });
});

describe("Today request lifecycle", () => {
  it("completes a Task through its owning service and reloads the derived review", async () => {
    const completedTask: Task = {
      id: "due-today",
      title: "今日任务",
      details: "附上图表",
      deadline: "2026-09-01",
      completed: true,
      createdAt: 10,
      updatedAt: 110,
      completedAt: 110,
    };
    const refreshedReview: DailyReview = {
      ...review,
      tasks: review.tasks.filter((task) => task.id !== "due-today"),
      generatedAt: 110,
    };
    const reviewService: DailyReviewService = {
      getDailyReview: vi.fn(async () => refreshedReview),
    };
    const taskService = {
      setCompleted: vi.fn(async () => completedTask),
    };
    const snapshots: TodayPageSnapshot[] = [];
    const coordinator = new TodayPageCoordinator(
      reviewService,
      taskService,
      (snapshot) => snapshots.push(snapshot),
    );

    await coordinator.completeTask(review.tasks[1]);

    expect(taskService.setCompleted).toHaveBeenCalledWith(
      "due-today",
      true,
      expect.any(AbortSignal),
    );
    expect(reviewService.getDailyReview).toHaveBeenCalledOnce();
    expect(snapshots.at(-1)).toMatchObject({
      review: refreshedReview,
      loadState: "ready",
      busyTaskId: null,
      notice: "已完成“今日任务”。",
    });
  });

  it("aborts route-scoped work and ignores a late result after disposal", async () => {
    let finish: ((value: DailyReview) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    const reviewService: DailyReviewService = {
      getDailyReview: (signal) => {
        requestSignal = signal;
        return new Promise((resolve) => {
          finish = resolve;
        });
      },
    };
    const snapshots: TodayPageSnapshot[] = [];
    const coordinator = new TodayPageCoordinator(
      reviewService,
      { setCompleted: vi.fn() },
      (snapshot) => snapshots.push(snapshot),
    );

    const pending = coordinator.start();
    const publishedBeforeDispose = snapshots.length;
    coordinator.dispose();
    expect(requestSignal?.aborted).toBe(true);
    finish?.(review);
    await pending;

    expect(snapshots).toHaveLength(publishedBeforeDispose);
    expect(snapshots.at(-1)?.review).toBeNull();
  });
});
