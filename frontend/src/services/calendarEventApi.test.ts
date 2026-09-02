import { describe, expect, it, vi } from "vitest";

import { HttpCalendarEventService } from "./calendarEventApi";

const apiEvent = {
  id: "event-1",
  title: "Project review",
  start_at: "2026-09-04T17:00:00+08:00",
  end_at: "2026-09-04T18:00:00+08:00",
  details: "Discuss launch",
  created_at: 100,
  updated_at: 200,
};

const conflictingEvent = {
  ...apiEvent,
  id: "event-2",
  title: "Call",
  start_at: "2026-09-04T17:30:00+08:00",
  end_at: null,
  details: null,
};

const confirmation = {
  id: "confirmation-1",
  binding: {
    user_id: "local-user",
    conversation_id: "settings",
    tool: "calendar_event_delete",
    arguments: { event_id: "event-1" },
    initiating_context: [],
  },
  created_at: 300,
  expires_at: 400,
};

describe("HTTP Calendar Event service", () => {
  it("converts event and conflict fields and forwards cancellation to reads", async () => {
    const controller = new AbortController();
    const fetchRequest = vi.fn(async (input: RequestInfo | URL) =>
      Response.json(String(input).endsWith("event-1")
        ? { calendar_event: apiEvent, conflicts: [conflictingEvent] }
        : {
            calendar_events: [apiEvent, conflictingEvent],
            conflicts: { "event-1": [conflictingEvent], "event-2": [apiEvent] },
          }),
    );
    const service = new HttpCalendarEventService(fetchRequest);

    await expect(service.listCalendarEvents(controller.signal)).resolves.toEqual({
      calendarEvents: [
        {
          id: "event-1",
          title: "Project review",
          startAt: "2026-09-04T17:00:00+08:00",
          endAt: "2026-09-04T18:00:00+08:00",
          details: "Discuss launch",
          createdAt: 100,
          updatedAt: 200,
        },
        expect.objectContaining({ id: "event-2", endAt: null }),
      ],
      conflicts: {
        "event-1": [expect.objectContaining({ id: "event-2" })],
        "event-2": [expect.objectContaining({ id: "event-1" })],
      },
    });
    await expect(service.getCalendarEvent("event-1", controller.signal)).resolves
      .toMatchObject({
        calendarEvent: { id: "event-1", startAt: apiEvent.start_at },
        conflicts: [{ id: "event-2" }],
      });
    expect(fetchRequest).toHaveBeenNthCalledWith(
      1,
      "/api/settings/calendar-events",
      { signal: controller.signal },
    );
    expect(fetchRequest).toHaveBeenNthCalledWith(
      2,
      "/api/settings/calendar-events/event-1",
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
      return Response.json({ calendar_event: apiEvent, conflicts: [] });
    });
    const service = new HttpCalendarEventService(fetchRequest);
    const draft = {
      title: "Project review",
      startAt: "2026-09-04T17:00",
      endAt: "2026-09-04T18:00",
      details: "Discuss launch",
    };

    await service.createCalendarEvent(draft);
    await service.updateCalendarEvent("event-1", draft);
    const pending = await service.requestDeleteConfirmation("event-1");
    await service.decideDelete("event-1", pending, "accept");

    expect(requests.map(({ url, init }) => [url, init?.method ?? "GET"])).toEqual([
      ["/api/settings/calendar-events", "POST"],
      ["/api/settings/calendar-events/event-1", "PATCH"],
      ["/api/settings/calendar-events/event-1/delete-confirmation", "POST"],
      ["/api/settings/calendar-events/event-1", "DELETE"],
    ]);
    expect(JSON.parse(String(requests[0].init?.body))).toEqual({
      title: "Project review",
      start_at: "2026-09-04T17:00",
      end_at: "2026-09-04T18:00",
      details: "Discuss launch",
    });
    expect(JSON.parse(String(requests.at(-1)?.init?.body))).toEqual({
      confirmation_id: "confirmation-1",
      binding: confirmation.binding,
      decision: "accept",
    });
  });

  it("reports HTTP failures without replacing their status", async () => {
    const service = new HttpCalendarEventService(
      async () => new Response(null, { status: 503 }),
    );

    await expect(service.listCalendarEvents()).rejects.toMatchObject({
      status: 503,
    });
  });
});
