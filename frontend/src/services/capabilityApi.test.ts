import { describe, expect, it, vi } from "vitest";

import { HttpCapabilityService } from "./capabilityApi";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpCapabilityService", () => {
  it("loads tool metadata and Skill state through the existing capability shape", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({
      tools: [{
        name: "status_read",
        description: "Read local status.",
        input_schema: { type: "object", properties: {} },
        permission_requirements: ["status:read"],
        side_effect: "none",
        risk: "low",
      }],
      skills: [{ name: "plain_language", description: "Explain status.", enabled: true }],
    }));
    const service = new HttpCapabilityService(fetchRequest);

    const capabilities = await service.getCapabilities();

    expect(fetchRequest).toHaveBeenCalledWith(
      "/api/settings/capabilities",
      { signal: undefined },
    );
    expect(capabilities.tools[0]).toMatchObject({
      name: "status_read",
      inputSchema: { type: "object", properties: {} },
      permissionRequirements: ["status:read"],
      sideEffect: "none",
      risk: "low",
    });
    expect(capabilities.skills[0].enabled).toBe(true);
  });

  it("updates Skill enablement without mixing Provider state into the request", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({
      skill: { name: "plain_language", description: "Explain status.", enabled: false },
      event: { type: "skill_enablement_changed" },
    }));
    const service = new HttpCapabilityService(fetchRequest);

    const skill = await service.setSkillEnabled("plain/language", false);

    expect(fetchRequest.mock.calls[0][0]).toBe(
      "/api/settings/skills/plain%2Flanguage/enabled",
    );
    expect(fetchRequest.mock.calls[0][1]).toMatchObject({ method: "PUT" });
    expect(JSON.parse(String(fetchRequest.mock.calls[0][1]?.body))).toEqual({
      enabled: false,
    });
    expect(skill.enabled).toBe(false);
  });
});
