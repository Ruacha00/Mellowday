import { describe, expect, it, vi } from "vitest";

import { HttpProactiveChatService } from "./proactiveChatApi";

const apiSettings = {
  enabled: false,
  quiet_hours_start: "22:00",
  quiet_hours_end: "08:00",
  cooldown_seconds: 3600,
  daily_limit: 2,
  proactive_chat_style: "brief and low-pressure",
};

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpProactiveChatService", () => {
  it("loads and converts the existing settings contract", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({ settings: apiSettings }));
    const service = new HttpProactiveChatService(fetchRequest);

    const settings = await service.getSettings();

    expect(fetchRequest).toHaveBeenCalledWith(
      "/api/settings/proactive-chat",
      { signal: undefined },
    );
    expect(settings).toEqual({
      enabled: false,
      quietHoursStart: "22:00",
      quietHoursEnd: "08:00",
      cooldownSeconds: 3600,
      dailyLimit: 2,
      proactiveChatStyle: "brief and low-pressure",
    });
  });

  it("saves booleans, numbers, times, and style without changing the PUT shape", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({ settings: apiSettings }));
    const service = new HttpProactiveChatService(fetchRequest);

    await service.updateSettings({
      enabled: false,
      quietHoursStart: "22:00",
      quietHoursEnd: "08:00",
      cooldownSeconds: 3600,
      dailyLimit: 2,
      proactiveChatStyle: "brief and low-pressure",
    });

    const [path, init] = fetchRequest.mock.calls[0];
    expect(path).toBe("/api/settings/proactive-chat");
    expect(init).toMatchObject({ method: "PUT" });
    expect(JSON.parse(String(init?.body))).toEqual(apiSettings);
  });
});
