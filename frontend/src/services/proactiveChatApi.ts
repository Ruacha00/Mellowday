import { HttpResponseError } from "./conversationApi";

export interface ProactiveChatSettings {
  enabled: boolean;
  quietHoursStart: string;
  quietHoursEnd: string;
  cooldownSeconds: number;
  dailyLimit: number;
  proactiveChatStyle: string;
}

export interface ProactiveChatService {
  getSettings(signal?: AbortSignal): Promise<ProactiveChatSettings>;
  updateSettings(
    settings: ProactiveChatSettings,
    signal?: AbortSignal,
  ): Promise<ProactiveChatSettings>;
}

interface ApiProactiveChatSettings {
  enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  cooldown_seconds: number;
  daily_limit: number;
  proactive_chat_style: string;
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function convertSettings(settings: ApiProactiveChatSettings): ProactiveChatSettings {
  return {
    enabled: settings.enabled,
    quietHoursStart: settings.quiet_hours_start,
    quietHoursEnd: settings.quiet_hours_end,
    cooldownSeconds: settings.cooldown_seconds,
    dailyLimit: settings.daily_limit,
    proactiveChatStyle: settings.proactive_chat_style,
  };
}

function toApiSettings(settings: ProactiveChatSettings): ApiProactiveChatSettings {
  return {
    enabled: settings.enabled,
    quiet_hours_start: settings.quietHoursStart,
    quiet_hours_end: settings.quietHoursEnd,
    cooldown_seconds: settings.cooldownSeconds,
    daily_limit: settings.dailyLimit,
    proactive_chat_style: settings.proactiveChatStyle,
  };
}

export class HttpProactiveChatService implements ProactiveChatService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async getSettings(signal?: AbortSignal): Promise<ProactiveChatSettings> {
    const payload = await this.requestJson<{ settings: ApiProactiveChatSettings }>(
      "/api/settings/proactive-chat",
      { signal },
    );
    return convertSettings(payload.settings);
  }

  async updateSettings(
    settings: ProactiveChatSettings,
    signal?: AbortSignal,
  ): Promise<ProactiveChatSettings> {
    const payload = await this.requestJson<{ settings: ApiProactiveChatSettings }>(
      "/api/settings/proactive-chat",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toApiSettings(settings)),
        signal,
      },
    );
    return convertSettings(payload.settings);
  }

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
