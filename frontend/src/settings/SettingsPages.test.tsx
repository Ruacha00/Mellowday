import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { Persona, PersonaService } from "../services/personaApi";
import type { ProactiveChatService } from "../services/proactiveChatApi";
import { PersonaSettingsPage, validatePersona } from "./PersonaSettingsPage";
import {
  ProactiveChatSettingsPage,
  validateProactiveChatDraft,
} from "./ProactiveChatSettingsPage";

const persona: Persona = {
  name: "Mellowday",
  identity: "a personal companion",
  character: "warm and truthful",
  speakingStyle: "calm and clear",
  relationshipFraming: "a trusted companion",
  conversationalBoundaries: "do not invent facts",
  proactiveChatStyle: "brief and low-pressure",
};

describe("Settings Persona and Proactive Chat pages", () => {
  it("keeps loading and management copy neutral", () => {
    const personaService: PersonaService = {
      getPersona: vi.fn(),
      updatePersona: vi.fn(),
    };
    const proactiveService: ProactiveChatService = {
      getSettings: vi.fn(),
      updateSettings: vi.fn(),
    };

    const personaMarkup = renderToStaticMarkup(
      <PersonaSettingsPage service={personaService} />,
    );
    const proactiveMarkup = renderToStaticMarkup(
      <ProactiveChatSettingsPage service={proactiveService} />,
    );

    expect(personaMarkup).toContain("正在加载人格设定");
    expect(proactiveMarkup).toContain("正在加载主动聊天设置");
    expect(personaMarkup + proactiveMarkup).not.toMatch(/亲爱的|宝贝|陪你聊聊/u);
  });

  it("identifies the first empty Persona field for focusable validation", () => {
    expect(validatePersona({ ...persona, speakingStyle: "  " })).toEqual({
      field: "speakingStyle",
      message: "请输入表达方式。",
    });
    expect(validatePersona(persona)).toBeNull();
  });

  it("validates Proactive Chat values and returns a typed backend draft", () => {
    expect(validateProactiveChatDraft({
      enabled: true,
      quietHoursStart: "24:00",
      quietHoursEnd: "08:00",
      cooldownSeconds: "60",
      dailyLimit: "2",
      proactiveChatStyle: "brief",
    })).toMatchObject({ field: "quietHoursStart" });
    expect(validateProactiveChatDraft({
      enabled: true,
      quietHoursStart: "22:00",
      quietHoursEnd: "08:00",
      cooldownSeconds: "",
      dailyLimit: "2",
      proactiveChatStyle: "brief",
    })).toMatchObject({ field: "cooldownSeconds" });
    expect(validateProactiveChatDraft({
      enabled: true,
      quietHoursStart: "22:00",
      quietHoursEnd: "08:00",
      cooldownSeconds: "60",
      dailyLimit: "2",
      proactiveChatStyle: " brief ",
    }).settings).toEqual({
      enabled: true,
      quietHoursStart: "22:00",
      quietHoursEnd: "08:00",
      cooldownSeconds: 60,
      dailyLimit: 2,
      proactiveChatStyle: "brief",
    });
  });
});
