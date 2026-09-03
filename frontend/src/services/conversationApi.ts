export type ChatRole = "user" | "assistant";
export type ChatMessageSource = "reminder" | "proactive_chat";

export interface ChatMessage {
  role: ChatRole;
  content: string;
  source?: ChatMessageSource | null;
}

export interface RuntimeEvent {
  sequence: number;
  type: string;
  occurredAt: number;
  conversationId: string | null;
  details: Record<string, unknown>;
}

export interface ConfirmationBinding {
  userId: string;
  conversationId: string;
  tool: string;
  arguments: Record<string, unknown>;
  initiatingContext: ChatMessage[];
}

export interface PendingConfirmation {
  id: string;
  binding: ConfirmationBinding;
  createdAt: number;
  expiresAt: number;
}

export interface Turn {
  chatContent: ChatMessage;
  stopReason: string;
  events: RuntimeEvent[];
  confirmation: PendingConfirmation | null;
}

export interface ConversationSummary {
  conversationId: string;
  messageCount: number;
  characterCount: number;
  createdAt: number;
  updatedAt: number;
  title?: string | null;
  preview?: string | null;
}

export interface Conversation {
  summary: ConversationSummary;
  messages: ChatMessage[];
}

export type ConfirmationDecision = "accept" | "reject";

export interface ResetResult {
  ok: boolean;
  decision: ConfirmationDecision;
  removedMessages: number;
}

export interface ConversationService {
  listConversations(signal?: AbortSignal): Promise<ConversationSummary[]>;
  loadConversation(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<Conversation | null>;
  renameConversation(
    conversationId: string,
    title: string,
    signal?: AbortSignal,
  ): Promise<ConversationSummary>;
  sendMessage(
    conversationId: string,
    content: string,
    signal?: AbortSignal,
  ): Promise<Turn>;
  listPendingConfirmations(
    signal?: AbortSignal,
  ): Promise<PendingConfirmation[]>;
  decideConfirmation(
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<Turn>;
  requestResetConfirmation(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation>;
  decideReset(
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<ResetResult>;
}

interface ApiChatMessage {
  role: ChatRole;
  content: string;
  source?: ChatMessageSource | null;
}

interface ApiRuntimeEvent {
  sequence: number;
  type: string;
  occurred_at: number;
  conversation_id: string | null;
  details: Record<string, unknown>;
}

interface ApiConfirmationBinding {
  user_id: string;
  conversation_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  initiating_context: ApiChatMessage[];
}

interface ApiPendingConfirmation {
  id: string;
  binding: ApiConfirmationBinding;
  created_at: number;
  expires_at: number;
}

export interface ApiTurnResponse {
  chat_content: ApiChatMessage;
  stop_reason: string;
  events: ApiRuntimeEvent[];
  confirmation: ApiPendingConfirmation | null;
}

interface ApiConversationSummary {
  conversation_id: string;
  message_count: number;
  character_count: number;
  created_at: number;
  updated_at: number;
  title?: string | null;
  preview?: string | null;
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

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

function convertConversationSummary(
  summary: ApiConversationSummary,
): ConversationSummary {
  return {
    conversationId: summary.conversation_id,
    messageCount: summary.message_count,
    characterCount: summary.character_count,
    createdAt: summary.created_at,
    updatedAt: summary.updated_at,
    title: summary.title ?? null,
    preview: summary.preview ?? null,
  };
}

export function convertTurnResponse(response: ApiTurnResponse): Turn {
  return {
    chatContent: response.chat_content,
    stopReason: response.stop_reason,
    events: response.events.map((event) => ({
      sequence: event.sequence,
      type: event.type,
      occurredAt: event.occurred_at,
      conversationId: event.conversation_id,
      details: event.details,
    })),
    confirmation:
      response.confirmation === null
        ? null
        : convertConfirmation(response.confirmation),
  };
}

export class HttpResponseError extends Error {
  constructor(readonly status: number) {
    super(`Request failed with ${status}`);
  }
}

export class HttpConversationService implements ConversationService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listConversations(
    signal?: AbortSignal,
  ): Promise<ConversationSummary[]> {
    const payload = await this.requestJson<{
      conversations: ApiConversationSummary[];
    }>("/api/conversations", { signal });
    return payload.conversations.map(convertConversationSummary);
  }

  async loadConversation(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<Conversation | null> {
    const response = await this.fetchRequest(
      this.endpoint(`/api/conversations/${encodeURIComponent(conversationId)}`),
      { signal },
    );
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    const payload = (await response.json()) as {
      conversation: ApiConversationSummary;
      messages: ApiChatMessage[];
    };
    return {
      summary: convertConversationSummary(payload.conversation),
      messages: payload.messages,
    };
  }

  async renameConversation(
    conversationId: string,
    title: string,
    signal?: AbortSignal,
  ): Promise<ConversationSummary> {
    const payload = await this.requestJson<{
      conversation: ApiConversationSummary;
    }>(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
      signal,
    });
    return convertConversationSummary(payload.conversation);
  }

  async sendMessage(
    conversationId: string,
    content: string,
    signal?: AbortSignal,
  ): Promise<Turn> {
    const payload = await this.requestJson<ApiTurnResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, content }),
      signal,
    });
    return convertTurnResponse(payload);
  }

  async listPendingConfirmations(
    signal?: AbortSignal,
  ): Promise<PendingConfirmation[]> {
    const payload = await this.requestJson<{
      confirmations: ApiPendingConfirmation[];
    }>("/api/settings/confirmations", { signal });
    return payload.confirmations.map(convertConfirmation);
  }

  async decideConfirmation(
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<Turn> {
    const payload = await this.requestJson<{ turn: ApiTurnResponse }>(
      `/api/settings/confirmations/${encodeURIComponent(confirmation.id)}/decision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          binding: toApiBinding(confirmation.binding),
        }),
        signal,
      },
    );
    return convertTurnResponse(payload.turn);
  }

  async requestResetConfirmation(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation> {
    const payload = await this.requestJson<{
      confirmation: ApiPendingConfirmation;
    }>(
      `/api/conversations/${encodeURIComponent(conversationId)}/reset-confirmation`,
      { method: "POST", signal },
    );
    return convertConfirmation(payload.confirmation);
  }

  async decideReset(
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<ResetResult> {
    const payload = await this.requestJson<{
      ok: boolean;
      decision: ConfirmationDecision;
      removed_messages: number;
    }>(
      `/api/conversations/${encodeURIComponent(confirmation.binding.conversationId)}/reset`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation_id: confirmation.id,
          binding: toApiBinding(confirmation.binding),
          decision,
        }),
        signal,
      },
    );
    return {
      ok: payload.ok,
      decision: payload.decision,
      removedMessages: payload.removed_messages,
    };
  }

  private endpoint(path: string): string {
    return `${this.basePath}${path}`;
  }

  private async requestJson<T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> {
    const response = await this.fetchRequest(this.endpoint(path), init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
