import { describe, expect, it, vi } from "vitest";

import { HttpDiagnosticsService } from "./diagnosticsApi";

describe("HttpDiagnosticsService", () => {
  it("preserves status, event, and log facts through the existing contracts", async () => {
    const fetchRequest = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        backend: { ok: true, service: "mellowday" },
        provider: {
          configured: true,
          enabled: true,
          id: "provider-1",
          model: "small-model",
          name: "Local model",
          health: { state: "available" },
        },
        sessions: 2,
        pending_confirmations: 1,
        tools: 3,
        skills: 4,
        event_cursor: 8,
        log_cursor: 9,
        single_user: true,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        events: [{
          sequence: 8,
          type: "turn_completed",
          occurred_at: 42,
          conversation_id: "main",
          details: { stop_reason: "final" },
        }],
        cursor: 8,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        logs: [{
          sequence: 9,
          occurred_at: 43,
          level: "WARNING",
          logger: "mellowday.test",
          message: "diagnostic marker",
        }],
        cursor: 9,
      }), { status: 200 }));
    const service = new HttpDiagnosticsService(fetchRequest, "https://example.test");
    const controller = new AbortController();

    await expect(service.getStatus(controller.signal)).resolves.toMatchObject({
      sessions: 2,
      pendingConfirmations: 1,
      eventCursor: 8,
      logCursor: 9,
    });
    await expect(service.listEvents({
      since: 4,
      type: "turn_completed",
      conversationId: "main",
    }, controller.signal)).resolves.toEqual({
      events: [{
        sequence: 8,
        type: "turn_completed",
        occurredAt: 42,
        conversationId: "main",
        details: { stop_reason: "final" },
      }],
      cursor: 8,
    });
    await expect(service.listLogs({
      since: 5,
      level: "WARNING",
      search: "marker",
    }, controller.signal)).resolves.toEqual({
      logs: [{
        sequence: 9,
        occurredAt: 43,
        level: "WARNING",
        logger: "mellowday.test",
        message: "diagnostic marker",
      }],
      cursor: 9,
    });

    expect(fetchRequest).toHaveBeenNthCalledWith(
      1,
      "https://example.test/api/settings/status",
      { signal: controller.signal },
    );
    expect(fetchRequest).toHaveBeenNthCalledWith(
      2,
      "https://example.test/api/events/recent?since=4&limit=100&type=turn_completed&conversation_id=main",
      { signal: controller.signal },
    );
    expect(fetchRequest).toHaveBeenNthCalledWith(
      3,
      "https://example.test/api/logs/recent?since=5&limit=100&level=WARNING&q=marker",
      { signal: controller.signal },
    );
  });
});
