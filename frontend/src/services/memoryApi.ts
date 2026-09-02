import {
  HttpResponseError,
  type ConfirmationBinding,
  type ConfirmationDecision,
  type PendingConfirmation,
} from "./conversationApi";

export type MemoryKind = "preference" | "fact" | "important";
export type MemoryProvenance = "explicit" | "automatic";

export interface Memory {
  id: string;
  content: string;
  kind: MemoryKind;
  provenance: MemoryProvenance;
  sourceConversationId: string | null;
  createdAt: number;
  updatedAt: number;
}

export interface MemoryDraft {
  content: string;
  kind: MemoryKind;
}

export interface MemoryDeleteResult {
  ok: boolean;
  decision: ConfirmationDecision;
}

export interface MemoryService {
  listMemories(query?: string, signal?: AbortSignal): Promise<Memory[]>;
  updateMemory(
    memoryId: string,
    draft: MemoryDraft,
    signal?: AbortSignal,
  ): Promise<Memory>;
  requestDeleteConfirmation(
    memoryId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation>;
  decideDelete(
    memoryId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<MemoryDeleteResult>;
}

interface ApiMemory {
  id: string;
  content: string;
  kind: MemoryKind;
  provenance: MemoryProvenance;
  source_conversation_id: string | null;
  created_at: number;
  updated_at: number;
}

interface ApiConfirmationBinding {
  user_id: string;
  conversation_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  initiating_context: Array<{ role: "user" | "assistant"; content: string }>;
}

interface ApiPendingConfirmation {
  id: string;
  binding: ApiConfirmationBinding;
  created_at: number;
  expires_at: number;
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function convertMemory(memory: ApiMemory): Memory {
  return {
    id: memory.id,
    content: memory.content,
    kind: memory.kind,
    provenance: memory.provenance,
    sourceConversationId: memory.source_conversation_id,
    createdAt: memory.created_at,
    updatedAt: memory.updated_at,
  };
}

function convertBinding(binding: ApiConfirmationBinding): ConfirmationBinding {
  return {
    userId: binding.user_id,
    conversationId: binding.conversation_id,
    tool: binding.tool,
    arguments: binding.arguments,
    initiatingContext: binding.initiating_context,
  };
}

function toApiBinding(binding: ConfirmationBinding): ApiConfirmationBinding {
  return {
    user_id: binding.userId,
    conversation_id: binding.conversationId,
    tool: binding.tool,
    arguments: binding.arguments,
    initiating_context: binding.initiatingContext,
  };
}

function convertConfirmation(
  confirmation: ApiPendingConfirmation,
): PendingConfirmation {
  return {
    id: confirmation.id,
    binding: convertBinding(confirmation.binding),
    createdAt: confirmation.created_at,
    expiresAt: confirmation.expires_at,
  };
}

export class HttpMemoryService implements MemoryService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listMemories(query = "", signal?: AbortSignal): Promise<Memory[]> {
    const parameters = new URLSearchParams({ q: query });
    const payload = await this.requestJson<{ memories: ApiMemory[] }>(
      `/api/settings/memories?${parameters.toString()}`,
      { signal },
    );
    return payload.memories.map(convertMemory);
  }

  async updateMemory(
    memoryId: string,
    draft: MemoryDraft,
    signal?: AbortSignal,
  ): Promise<Memory> {
    const payload = await this.requestJson<{ memory: ApiMemory }>(
      `/api/settings/memories/${encodeURIComponent(memoryId)}`,
      this.jsonRequest("PATCH", draft, signal),
    );
    return convertMemory(payload.memory);
  }

  async requestDeleteConfirmation(
    memoryId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation> {
    const payload = await this.requestJson<{
      confirmation: ApiPendingConfirmation;
    }>(
      `/api/settings/memories/${encodeURIComponent(memoryId)}/delete-confirmation`,
      { method: "POST", signal },
    );
    return convertConfirmation(payload.confirmation);
  }

  decideDelete(
    memoryId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<MemoryDeleteResult> {
    return this.requestJson<MemoryDeleteResult>(
      `/api/settings/memories/${encodeURIComponent(memoryId)}`,
      this.jsonRequest(
        "DELETE",
        {
          confirmation_id: confirmation.id,
          binding: toApiBinding(confirmation.binding),
          decision,
        },
        signal,
      ),
    );
  }

  private jsonRequest(
    method: string,
    body: unknown,
    signal?: AbortSignal,
  ): RequestInit {
    return {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    };
  }

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
