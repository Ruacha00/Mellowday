import { describe, expect, it, vi } from "vitest";

import {
  HttpConversationService,
  convertTurnResponse,
  type PendingConfirmation,
} from "./conversationApi";
import {
  ApplicationLiveEventService,
  type EventSourcePort,
} from "./liveEvents";
import { LatestRequest } from "./requestLifecycle";

const pendingConfirmation: PendingConfirmation = {
  id: "confirmation-1",
  binding: {
    userId: "local-user",
    conversationId: "main",
    tool: "erase_note",
    arguments: { note_id: "note-1" },
    initiatingContext: [{ role: "user", content: "Erase note one." }],
  },
  createdAt: 100,
  expiresAt: 200,
};

describe("conversation response conversion", () => {
  it("converts chat and confirmation fields without leaking wire names", () => {
    const turn = convertTurnResponse({
      chat_content: { role: "assistant", content: "Continue?" },
      stop_reason: "confirmation_pending",
      events: [
        {
          sequence: 7,
          type: "confirmation_pending",
          occurred_at: 101,
          conversation_id: "main",
          details: { tool: "erase_note" },
        },
      ],
      confirmation: {
        id: "confirmation-1",
        binding: {
          user_id: "local-user",
          conversation_id: "main",
          tool: "erase_note",
          arguments: { note_id: "note-1" },
          initiating_context: [
            { role: "user", content: "Erase note one." },
          ],
        },
        created_at: 100,
        expires_at: 200,
      },
    });

    expect(turn).toEqual({
      chatContent: { role: "assistant", content: "Continue?" },
      stopReason: "confirmation_pending",
      events: [
        {
          sequence: 7,
          type: "confirmation_pending",
          occurredAt: 101,
          conversationId: "main",
          details: { tool: "erase_note" },
        },
      ],
      confirmation: pendingConfirmation,
    });
  });

  it("converts recent-conversation presentation fields", async () => {
    const service = new HttpConversationService(async () =>
      Response.json({
        conversations: [
          {
            conversation_id: "planning",
            message_count: 4,
            character_count: 72,
            created_at: 100,
            updated_at: 200,
            title: "Launch notes",
            preview: "First stored message",
          },
        ],
      }),
    );

    await expect(service.listConversations()).resolves.toEqual([
      {
        conversationId: "planning",
        messageCount: 4,
        characterCount: 72,
        createdAt: 100,
        updatedAt: 200,
        title: "Launch notes",
        preview: "First stored message",
      },
    ]);
  });
});

describe("confirmation requests", () => {
  it("carries the original binding through the two-step reset contract", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetchRequest = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ url: String(input), init });
      if (requests.length === 1) {
        return Response.json({
          confirmation: {
            id: "confirmation-1",
            binding: {
              user_id: "local-user",
              conversation_id: "main",
              tool: "conversation_history_reset",
              arguments: { conversation_id: "main" },
              initiating_context: [],
            },
            created_at: 100,
            expires_at: 200,
          },
          event: {},
        });
      }
      return Response.json({
        ok: true,
        decision: "accept",
        removed_messages: 2,
        event: {},
      });
    });
    const service = new HttpConversationService(fetchRequest);

    const confirmation = await service.requestResetConfirmation("main");
    const result = await service.decideReset(confirmation, "accept");

    expect(result).toEqual({
      ok: true,
      decision: "accept",
      removedMessages: 2,
    });
    expect(requests).toEqual([
      {
        url: "/api/conversations/main/reset-confirmation",
        init: { method: "POST", signal: undefined },
      },
      {
        url: "/api/conversations/main/reset",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation_id: "confirmation-1",
            binding: {
              user_id: "local-user",
              conversation_id: "main",
              tool: "conversation_history_reset",
              arguments: { conversation_id: "main" },
              initiating_context: [],
            },
            decision: "accept",
          }),
          signal: undefined,
        },
      },
    ]);
  });

  it("decides a pending tool confirmation through the typed service", async () => {
    const fetchRequest = vi.fn(async () =>
      Response.json({
        turn: {
          chat_content: { role: "assistant", content: "Left it alone." },
          stop_reason: "confirmation_rejected",
          events: [],
          confirmation: null,
        },
      }),
    );
    const service = new HttpConversationService(fetchRequest);

    const turn = await service.decideConfirmation(
      pendingConfirmation,
      "reject",
    );

    expect(turn.stopReason).toBe("confirmation_rejected");
    expect(fetchRequest).toHaveBeenCalledWith(
      "/api/settings/confirmations/confirmation-1/decision",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          decision: "reject",
          binding: {
            user_id: "local-user",
            conversation_id: "main",
            tool: "erase_note",
            arguments: { note_id: "note-1" },
            initiating_context: [
              { role: "user", content: "Erase note one." },
            ],
          },
        }),
      }),
    );
  });
});

class FakeEventSource implements EventSourcePort {
  readonly listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>();

  addEventListener(
    type: string,
    listener: (event: MessageEvent<string>) => void,
  ): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  close = vi.fn();

  emit(type: string, payload: object): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(payload) } as MessageEvent<string>);
    }
  }
}

describe("application live-event ownership", () => {
  it("keeps one connection across route subscriptions and appends each delivery once", () => {
    const sources: FakeEventSource[] = [];
    const urls: string[] = [];
    const service = new ApplicationLiveEventService({
      conversationId: "main",
      startedAt: 123.5,
      createEventSource: (url) => {
        urls.push(url);
        const source = new FakeEventSource();
        sources.push(source);
        return source;
      },
    });
    const firstRouteEvents: string[] = [];
    const secondRouteEvents: string[] = [];

    service.start();
    service.start();
    const leaveFirstRoute = service.subscribe((event) => {
      firstRouteEvents.push(event.message.content);
    });
    leaveFirstRoute();
    service.subscribe((event) => {
      secondRouteEvents.push(event.message.content);
    });

    sources[0].emit("reminder", {
      reminder_id: "reminder-1",
      role: "assistant",
      content: "Mellowday reminder: Join the call",
      due_at: 122,
      occurred_at: 124,
    });
    sources[0].emit("reminder", {
      reminder_id: "reminder-1",
      role: "assistant",
      content: "Mellowday reminder: Join the call",
      due_at: 122,
      occurred_at: 124,
    });
    sources[0].emit("proactive_chat", {
      proactive_chat_id: "proactive-1",
      role: "assistant",
      content: "How is your afternoon going?",
      occurred_at: 125,
    });
    sources[0].emit("proactive_chat", {
      proactive_chat_id: "proactive-1",
      role: "assistant",
      content: "How is your afternoon going?",
      occurred_at: 125,
    });

    expect(urls).toEqual([
      "/api/conversations/main/live?after=123.5",
    ]);
    expect(sources).toHaveLength(1);
    expect(firstRouteEvents).toEqual([]);
    expect(secondRouteEvents).toEqual([
      "Mellowday reminder: Join the call",
      "How is your afternoon going?",
    ]);
  });
});

describe("obsolete request handling", () => {
  it("aborts the previous request and ignores its late response", async () => {
    const requests = new LatestRequest();
    let finishFirst: ((value: string) => void) | undefined;
    let firstSignal: AbortSignal | undefined;
    const first = requests.run((signal) => {
      firstSignal = signal;
      return new Promise<string>((resolve) => {
        finishFirst = resolve;
      });
    });

    const second = requests.run(async () => "new route");

    expect(firstSignal?.aborted).toBe(true);
    await expect(second).resolves.toEqual({
      status: "current",
      value: "new route",
    });
    finishFirst?.("old route");
    await expect(first).resolves.toEqual({ status: "obsolete" });
  });
});
