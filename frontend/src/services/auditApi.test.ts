import { describe, expect, it, vi } from "vitest";

import { HttpAuditService } from "./auditApi";

describe("HttpAuditService", () => {
  it("preserves the existing audit facts while converting field names", async () => {
    const fetchRequest = vi.fn(async () => new Response(JSON.stringify({
      events: [{
        sequence: 7,
        type: "tool_failed",
        occurred_at: 42,
        conversation_id: "main",
        details: { tool: "save_note", reason: "backend unavailable" },
      }],
    }), { status: 200 }));
    const service = new HttpAuditService(fetchRequest, "https://example.test");
    const controller = new AbortController();

    await expect(service.listRecords(controller.signal)).resolves.toEqual([{
      sequence: 7,
      type: "tool_failed",
      occurredAt: 42,
      conversationId: "main",
      details: { tool: "save_note", reason: "backend unavailable" },
    }]);
    expect(fetchRequest).toHaveBeenCalledWith(
      "https://example.test/api/settings/audit",
      { signal: controller.signal },
    );
  });
});
