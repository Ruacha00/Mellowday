import { describe, expect, it, vi } from "vitest";

import { HttpDailyReviewService } from "./dailyReviewApi";

const apiReview = {
  date: "2026-09-01",
  timezone: "Asia/Shanghai",
  generated_at: 100,
  tasks: [{
    id: "task-1",
    title: "提交报告",
    details: "附上图表",
    deadline: "2026-09-01",
    timing: "due_today",
  }],
  reminders: [{
    id: "reminder-1",
    message: "参加例会",
    due_at: "2026-09-01T10:00:00+08:00",
    delivery_state: "scheduled",
    task_id: null,
    timing: "upcoming",
  }],
  calendar_events: [{
    id: "event-1",
    title: "午餐",
    start_at: "2026-09-01T12:00:00+08:00",
    end_at: null,
    details: null,
    timing: "upcoming",
  }],
  notes: [{
    id: "note-1",
    title: "会议准备",
    content: "带上数据",
    updated_at: 90,
    relevance: "updated_today",
  }],
} as const;

describe("HTTP Daily Review service", () => {
  it("converts the derived review and forwards cancellation", async () => {
    const controller = new AbortController();
    const fetchRequest = vi.fn(async () => Response.json({ daily_review: apiReview }));
    const service = new HttpDailyReviewService(fetchRequest, "/root");

    await expect(service.getDailyReview(controller.signal)).resolves.toEqual({
      date: "2026-09-01",
      timezone: "Asia/Shanghai",
      generatedAt: 100,
      tasks: [{
        id: "task-1",
        title: "提交报告",
        details: "附上图表",
        deadline: "2026-09-01",
        timing: "due_today",
      }],
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
        details: null,
        timing: "upcoming",
      }],
      notes: [{
        id: "note-1",
        title: "会议准备",
        content: "带上数据",
        updatedAt: 90,
        relevance: "updated_today",
      }],
    });
    expect(fetchRequest).toHaveBeenCalledWith(
      "/root/api/settings/daily-review",
      { signal: controller.signal },
    );
  });

  it("preserves HTTP failure status", async () => {
    const service = new HttpDailyReviewService(
      async () => new Response(null, { status: 503 }),
    );

    await expect(service.getDailyReview()).rejects.toMatchObject({ status: 503 });
  });
});
