import { describe, expect, it, vi } from "vitest";

import { HttpMemoryService } from "./memoryApi";

const apiMemory = {
  id: "memory/1",
  content: "I prefer concise replies.",
  kind: "preference" as const,
  provenance: "explicit" as const,
  source_conversation_id: "main",
  created_at: 10,
  updated_at: 12,
};

const apiConfirmation = {
  id: "confirmation-1",
  binding: {
    user_id: "local-user",
    conversation_id: "settings",
    tool: "memory_forget",
    arguments: { memory_id: "memory/1" },
    initiating_context: [],
  },
  created_at: 20,
  expires_at: 80,
};

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpMemoryService", () => {
  it("searches through the existing Memory list contract and converts fields", async () => {
    const fetchRequest = vi.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => jsonResponse({ memories: [apiMemory] }));
    const service = new HttpMemoryService(fetchRequest, "https://example.test");
    const controller = new AbortController();

    const memories = await service.listMemories("concise & clear", controller.signal);

    expect(fetchRequest).toHaveBeenCalledWith(
      "https://example.test/api/settings/memories?q=concise+%26+clear",
      { signal: controller.signal },
    );
    expect(memories).toEqual([{
      id: "memory/1",
      content: "I prefer concise replies.",
      kind: "preference",
      provenance: "explicit",
      sourceConversationId: "main",
      createdAt: 10,
      updatedAt: 12,
    }]);
  });

  it("edits Memory without changing the backend request shape", async () => {
    const fetchRequest = vi.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => jsonResponse({ memory: apiMemory }));
    const service = new HttpMemoryService(fetchRequest);

    await service.updateMemory("memory/1", {
      content: "I prefer detailed replies.",
      kind: "important",
    });

    const [path, init] = fetchRequest.mock.calls[0];
    expect(path).toBe("/api/settings/memories/memory%2F1");
    expect(init).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(String(init?.body))).toEqual({
      content: "I prefer detailed replies.",
      kind: "important",
    });
  });

  it("round-trips the confirmation binding before deletion", async () => {
    const fetchRequest = vi
      .fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValueOnce(jsonResponse({ confirmation: apiConfirmation }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, decision: "accept" }));
    const service = new HttpMemoryService(fetchRequest);

    const confirmation = await service.requestDeleteConfirmation("memory/1");
    const result = await service.decideDelete(
      "memory/1",
      confirmation,
      "accept",
    );

    expect(confirmation.binding).toMatchObject({
      userId: "local-user",
      conversationId: "settings",
      tool: "memory_forget",
      arguments: { memory_id: "memory/1" },
    });
    const [path, init] = fetchRequest.mock.calls[1];
    expect(path).toBe("/api/settings/memories/memory%2F1");
    expect(init).toMatchObject({ method: "DELETE" });
    expect(JSON.parse(String(init?.body))).toEqual({
      confirmation_id: "confirmation-1",
      binding: apiConfirmation.binding,
      decision: "accept",
    });
    expect(result).toEqual({ ok: true, decision: "accept" });
  });
});
