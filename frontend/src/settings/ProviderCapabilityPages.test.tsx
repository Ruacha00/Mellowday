import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { CapabilityService } from "../services/capabilityApi";
import type { ProviderService } from "../services/providerApi";
import { CapabilitySettingsPage } from "./CapabilitySettingsPage";
import {
  ProviderSettingsPage,
  validateProviderDraft,
} from "./ProviderSettingsPage";

describe("Settings Provider and Capability pages", () => {
  it("renders neutral route-owned loading states without credential content", () => {
    const providerService: ProviderService = {
      listProviders: vi.fn(),
      createProvider: vi.fn(),
      updateProvider: vi.fn(),
      setProviderEnabled: vi.fn(),
      selectProvider: vi.fn(),
      validateProvider: vi.fn(),
    };
    const capabilityService: CapabilityService = {
      getCapabilities: vi.fn(),
      setSkillEnabled: vi.fn(),
    };

    const markup = renderToStaticMarkup(
      <>
        <ProviderSettingsPage service={providerService} />
        <CapabilitySettingsPage service={capabilityService} />
      </>,
    );

    expect(markup).toContain("正在加载模型提供方");
    expect(markup).toContain("正在加载能力");
    expect(markup).not.toContain("api_key");
  });

  it("validates provider fields and preserves blank-key edits", () => {
    const draft = {
      name: " Local model ",
      baseUrl: "http://localhost:9000/v1",
      model: " chat-model ",
      apiKey: "",
      timeoutSeconds: "12",
      maxRetries: "2",
    };

    expect(validateProviderDraft(draft, false)).toMatchObject({
      field: "apiKey",
    });
    expect(validateProviderDraft(draft, true).input).toEqual({
      name: "Local model",
      baseUrl: "http://localhost:9000/v1",
      model: "chat-model",
      apiKey: "",
      timeoutSeconds: 12,
      maxRetries: 2,
    });
    expect(validateProviderDraft({ ...draft, maxRetries: "11" }, true)).toMatchObject({
      field: "maxRetries",
    });
  });
});
