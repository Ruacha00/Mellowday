import { HttpResponseError } from "./conversationApi";

export interface ProviderConfiguration {
  id: string;
  name: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  timeoutSeconds: number;
  maxRetries: number;
  enabled: boolean;
  selected: boolean;
}

export interface ProviderConfigurationInput {
  name: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  timeoutSeconds: number;
  maxRetries: number;
}

export interface ProviderValidationResult {
  valid: boolean;
  failure?: {
    code: string;
    retryable: boolean;
    attempts: number;
  };
}

export interface ProviderService {
  listProviders(signal?: AbortSignal): Promise<ProviderConfiguration[]>;
  createProvider(
    input: ProviderConfigurationInput,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration>;
  updateProvider(
    providerId: string,
    input: ProviderConfigurationInput,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration>;
  setProviderEnabled(
    providerId: string,
    enabled: boolean,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration>;
  selectProvider(
    providerId: string,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration>;
  validateProvider(
    providerId: string,
    signal?: AbortSignal,
  ): Promise<ProviderValidationResult>;
}

interface ApiProviderConfiguration {
  id: string;
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  timeout_seconds: number;
  max_retries: number;
  enabled: boolean;
  selected: boolean;
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function convertProvider(provider: ApiProviderConfiguration): ProviderConfiguration {
  return {
    id: provider.id,
    name: provider.name,
    baseUrl: provider.base_url,
    model: provider.model,
    apiKey: provider.api_key,
    timeoutSeconds: provider.timeout_seconds,
    maxRetries: provider.max_retries,
    enabled: provider.enabled,
    selected: provider.selected,
  };
}

function toApiProvider(input: ProviderConfigurationInput) {
  return {
    name: input.name,
    base_url: input.baseUrl,
    model: input.model,
    api_key: input.apiKey,
    timeout_seconds: input.timeoutSeconds,
    max_retries: input.maxRetries,
  };
}

export class HttpProviderService implements ProviderService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listProviders(signal?: AbortSignal): Promise<ProviderConfiguration[]> {
    const payload = await this.requestJson<{ providers: ApiProviderConfiguration[] }>(
      "/api/settings/providers",
      { signal },
    );
    return payload.providers.map(convertProvider);
  }

  async createProvider(
    input: ProviderConfigurationInput,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration> {
    return this.writeProvider(
      "/api/settings/providers",
      "POST",
      input,
      signal,
    );
  }

  async updateProvider(
    providerId: string,
    input: ProviderConfigurationInput,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration> {
    return this.writeProvider(
      `/api/settings/providers/${encodeURIComponent(providerId)}`,
      "PUT",
      input,
      signal,
    );
  }

  async setProviderEnabled(
    providerId: string,
    enabled: boolean,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration> {
    const payload = await this.requestJson<{ provider: ApiProviderConfiguration }>(
      `/api/settings/providers/${encodeURIComponent(providerId)}/enabled`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
        signal,
      },
    );
    return convertProvider(payload.provider);
  }

  async selectProvider(
    providerId: string,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration> {
    const payload = await this.requestJson<{ provider: ApiProviderConfiguration }>(
      `/api/settings/providers/${encodeURIComponent(providerId)}/select`,
      { method: "POST", signal },
    );
    return convertProvider(payload.provider);
  }

  async validateProvider(
    providerId: string,
    signal?: AbortSignal,
  ): Promise<ProviderValidationResult> {
    return this.requestJson<ProviderValidationResult>(
      `/api/settings/providers/${encodeURIComponent(providerId)}/validate`,
      { method: "POST", signal },
    );
  }

  private async writeProvider(
    path: string,
    method: "POST" | "PUT",
    input: ProviderConfigurationInput,
    signal?: AbortSignal,
  ): Promise<ProviderConfiguration> {
    const payload = await this.requestJson<{ provider: ApiProviderConfiguration }>(
      path,
      {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toApiProvider(input)),
        signal,
      },
    );
    return convertProvider(payload.provider);
  }

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
