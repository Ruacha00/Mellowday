import { describe, expect, it, vi } from "vitest";

import { HttpPersonaService } from "./personaApi";

const apiPersona = {
  name: "Mellowday",
  identity: "a personal companion",
  character: "warm and truthful",
  speaking_style: "calm and clear",
  relationship_framing: "a trusted companion",
  conversational_boundaries: "do not invent facts",
  proactive_chat_style: "brief and low-pressure",
};

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpPersonaService", () => {
  it("loads the existing Persona contract and converts its field names", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({ persona: apiPersona }));
    const service = new HttpPersonaService(fetchRequest, "https://example.test");
    const controller = new AbortController();

    const persona = await service.getPersona(controller.signal);

    expect(fetchRequest).toHaveBeenCalledWith(
      "https://example.test/api/settings/persona",
      { signal: controller.signal },
    );
    expect(persona).toMatchObject({
      speakingStyle: "calm and clear",
      relationshipFraming: "a trusted companion",
      proactiveChatStyle: "brief and low-pressure",
    });
  });

  it("saves through the existing PUT request shape", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({ persona: apiPersona }));
    const service = new HttpPersonaService(fetchRequest);

    await service.updatePersona({
      name: "Mellowday",
      identity: "a personal companion",
      character: "warm and truthful",
      speakingStyle: "calm and clear",
      relationshipFraming: "a trusted companion",
      conversationalBoundaries: "do not invent facts",
      proactiveChatStyle: "brief and low-pressure",
    });

    const [path, init] = fetchRequest.mock.calls[0];
    expect(path).toBe("/api/settings/persona");
    expect(init).toMatchObject({ method: "PUT" });
    expect(JSON.parse(String(init?.body))).toEqual(apiPersona);
  });
});
