import { describe, expect, it, vi } from "vitest";

import { HttpProviderService } from "./providerApi";

const apiProvider = {
  id: "provider-1",
  name: "Local model",
  base_url: "http://localhost:9000/v1",
  model: "chat-model",
  api_key: "••••cret",
  timeout_seconds: 12,
  max_retries: 1,
  enabled: true,
  selected: false,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpProviderService", () => {
  it("loads the existing provider response shape and keeps only the masked credential", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async () => jsonResponse({ providers: [apiProvider] }));
    const service = new HttpProviderService(fetchRequest);

    const providers = await service.listProviders();

    expect(fetchRequest).toHaveBeenCalledWith(
      "/api/settings/providers",
      { signal: undefined },
    );
    expect(providers).toEqual([{
      id: "provider-1",
      name: "Local model",
      baseUrl: "http://localhost:9000/v1",
      model: "chat-model",
      apiKey: "••••cret",
      timeoutSeconds: 12,
      maxRetries: 1,
      enabled: true,
      selected: false,
    }]);
  });

  it("preserves create and update request shapes, including blank-key edit semantics", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async (_input, init) => jsonResponse({ provider: apiProvider }, init?.method === "POST" ? 201 : 200));
    const service = new HttpProviderService(fetchRequest);
    const input = {
      name: "Local model",
      baseUrl: "http://localhost:9000/v1",
      model: "chat-model",
      apiKey: "local-secret",
      timeoutSeconds: 12,
      maxRetries: 1,
    };

    await service.createProvider(input);
    await service.updateProvider("provider-1", { ...input, apiKey: "" });

    expect(fetchRequest.mock.calls[0][0]).toBe("/api/settings/providers");
    expect(fetchRequest.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(fetchRequest.mock.calls[0][1]?.body))).toEqual({
      name: "Local model",
      base_url: "http://localhost:9000/v1",
      model: "chat-model",
      api_key: "local-secret",
      timeout_seconds: 12,
      max_retries: 1,
    });
    expect(fetchRequest.mock.calls[1][0]).toBe(
      "/api/settings/providers/provider-1",
    );
    expect(fetchRequest.mock.calls[1][1]).toMatchObject({ method: "PUT" });
    expect(JSON.parse(String(fetchRequest.mock.calls[1][1]?.body)).api_key).toBe("");
  });

  it("uses the existing enable, select, and validation routes", async () => {
    const fetchRequest = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(async (input) => String(input).endsWith("/validate")
      ? jsonResponse({ valid: false, failure: { code: "authentication", retryable: false, attempts: 1 } })
      : jsonResponse({ provider: apiProvider }));
    const service = new HttpProviderService(fetchRequest);

    await service.setProviderEnabled("provider/1", false);
    await service.selectProvider("provider/1");
    const validation = await service.validateProvider("provider/1");

    expect(fetchRequest.mock.calls.map(([path]) => path)).toEqual([
      "/api/settings/providers/provider%2F1/enabled",
      "/api/settings/providers/provider%2F1/select",
      "/api/settings/providers/provider%2F1/validate",
    ]);
    expect(JSON.parse(String(fetchRequest.mock.calls[0][1]?.body))).toEqual({
      enabled: false,
    });
    expect(validation).toEqual({
      valid: false,
      failure: { code: "authentication", retryable: false, attempts: 1 },
    });
  });
});
