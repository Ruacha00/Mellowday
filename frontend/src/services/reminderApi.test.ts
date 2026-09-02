import { describe, expect, it, vi } from "vitest";

import { HttpReminderService } from "./reminderApi";

const apiReminder = {
  id: "reminder-1",
  message: "Join the call",
  due_at: "2026-09-04T09:00:00+00:00",
  delivery_state: "scheduled",
  task_id: null,
  conversation_id: "main",
  created_at: 100,
  updated_at: 200,
  delivery_attempted_at: null,
  delivered_at: null,
  dismissed_at: null,
  cancelled_at: null,
  delivery_error: null,
};

const confirmation = {
  id: "confirmation-1",
  binding: {
    user_id: "local-user",
    conversation_id: "settings",
    tool: "reminder_delete",
    arguments: { reminder_id: "reminder-1" },
    initiating_context: [],
  },
  created_at: 300,
  expires_at: 400,
};

describe("HTTP Reminder service", () => {
  it("converts reminder fields and forwards cancellation to reads", async () => {
    const controller = new AbortController();
    const fetchRequest = vi.fn(async (input: RequestInfo | URL) =>
      Response.json(String(input).endsWith("reminder-1")
        ? { reminder: apiReminder }
        : { reminders: [apiReminder] }),
    );
    const service = new HttpReminderService(fetchRequest);

    await expect(service.listReminders(controller.signal)).resolves.toEqual([
      {
        id: "reminder-1",
        message: "Join the call",
        dueAt: "2026-09-04T09:00:00+00:00",
        deliveryState: "scheduled",
        taskId: null,
        conversationId: "main",
        createdAt: 100,
        updatedAt: 200,
        deliveryAttemptedAt: null,
        deliveredAt: null,
        dismissedAt: null,
        cancelledAt: null,
        deliveryError: null,
      },
    ]);
    await expect(service.getReminder("reminder-1", controller.signal)).resolves
      .toMatchObject({ id: "reminder-1", deliveryState: "scheduled" });
    expect(fetchRequest).toHaveBeenNthCalledWith(1, "/api/settings/reminders", {
      signal: controller.signal,
    });
    expect(fetchRequest).toHaveBeenNthCalledWith(
      2,
      "/api/settings/reminders/reminder-1",
      { signal: controller.signal },
    );
  });

  it("uses the existing mutation paths and preserves delete confirmation binding", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetchRequest = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith("/delete-confirmation")) {
        return Response.json({ confirmation });
      }
      if (init?.method === "DELETE") {
        return Response.json({ ok: true, decision: "accept" });
      }
      return Response.json({ reminder: apiReminder });
    });
    const service = new HttpReminderService(fetchRequest);
    const draft = {
      message: "Join the call",
      dueAt: "2026-09-04T09:00:00.000Z",
      taskId: null,
      conversationId: "main",
    };

    await service.createReminder(draft);
    await service.updateReminder("reminder-1", draft);
    await service.dismissReminder("reminder-1");
    await service.cancelReminder("reminder-1");
    const pending = await service.requestDeleteConfirmation("reminder-1");
    await service.decideDelete("reminder-1", pending, "accept");

    expect(requests.map(({ url, init }) => [url, init?.method ?? "GET"])).toEqual([
      ["/api/settings/reminders", "POST"],
      ["/api/settings/reminders/reminder-1", "PATCH"],
      ["/api/settings/reminders/reminder-1/dismiss", "POST"],
      ["/api/settings/reminders/reminder-1/cancel", "POST"],
      ["/api/settings/reminders/reminder-1/delete-confirmation", "POST"],
      ["/api/settings/reminders/reminder-1", "DELETE"],
    ]);
    expect(JSON.parse(String(requests[0].init?.body))).toEqual({
      message: "Join the call",
      due_at: "2026-09-04T09:00:00.000Z",
      task_id: null,
      conversation_id: "main",
    });
    expect(JSON.parse(String(requests.at(-1)?.init?.body))).toEqual({
      confirmation_id: "confirmation-1",
      binding: confirmation.binding,
      decision: "accept",
    });
  });

  it("reports HTTP failures without replacing their status", async () => {
    const service = new HttpReminderService(
      async () => new Response(null, { status: 503 }),
    );

    await expect(service.listReminders()).rejects.toMatchObject({ status: 503 });
  });
});
