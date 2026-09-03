import { HttpResponseError, type RuntimeEvent } from "./conversationApi";

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface DiagnosticsStatus {
  backend: { ok: boolean; service: string };
  provider: {
    configured: boolean;
    enabled: boolean;
    health?: { state: string };
    id?: string;
    model?: string;
    name: string;
  };
  sessions: number;
  pendingConfirmations: number;
  tools: number;
  skills: number;
  eventCursor: number;
  logCursor: number;
  singleUser: boolean;
}

export interface DiagnosticLog {
  sequence: number;
  occurredAt: number;
  level: string;
  logger: string;
  message: string;
}

export interface DiagnosticEventQuery {
  conversationId?: string;
  limit?: number;
  since?: number;
  type?: string;
}

export interface DiagnosticLogQuery {
  level?: string;
  limit?: number;
  search?: string;
  since?: number;
}

export interface DiagnosticEventPage {
  cursor: number;
  events: RuntimeEvent[];
}

export interface DiagnosticLogPage {
  cursor: number;
  logs: DiagnosticLog[];
}

export interface DiagnosticsService {
  getStatus(signal?: AbortSignal): Promise<DiagnosticsStatus>;
  listEvents(
    query?: DiagnosticEventQuery,
    signal?: AbortSignal,
  ): Promise<DiagnosticEventPage>;
  listLogs(
    query?: DiagnosticLogQuery,
    signal?: AbortSignal,
  ): Promise<DiagnosticLogPage>;
}

interface ApiDiagnosticsStatus {
  backend: DiagnosticsStatus["backend"];
  provider: DiagnosticsStatus["provider"];
  sessions: number;
  pending_confirmations: number;
  tools: number;
  skills: number;
  event_cursor: number;
  log_cursor: number;
  single_user: boolean;
}

interface ApiRuntimeEvent {
  sequence: number;
  type: string;
  occurred_at: number;
  conversation_id: string | null;
  details: Record<string, unknown>;
}

interface ApiDiagnosticLog {
  sequence: number;
  occurred_at: number;
  level: string;
  logger: string;
  message: string;
}

function convertEvent(event: ApiRuntimeEvent): RuntimeEvent {
  return {
    sequence: event.sequence,
    type: event.type,
    occurredAt: event.occurred_at,
    conversationId: event.conversation_id,
    details: event.details,
  };
}

function convertLog(log: ApiDiagnosticLog): DiagnosticLog {
  return {
    sequence: log.sequence,
    occurredAt: log.occurred_at,
    level: log.level,
    logger: log.logger,
    message: log.message,
  };
}

export class HttpDiagnosticsService implements DiagnosticsService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(globalThis),
    private readonly basePath = "",
  ) {}

  async getStatus(signal?: AbortSignal): Promise<DiagnosticsStatus> {
    const payload = await this.requestJson<ApiDiagnosticsStatus>(
      "/api/settings/status",
      signal,
    );
    return {
      backend: payload.backend,
      provider: payload.provider,
      sessions: payload.sessions,
      pendingConfirmations: payload.pending_confirmations,
      tools: payload.tools,
      skills: payload.skills,
      eventCursor: payload.event_cursor,
      logCursor: payload.log_cursor,
      singleUser: payload.single_user,
    };
  }

  async listEvents(
    query: DiagnosticEventQuery = {},
    signal?: AbortSignal,
  ): Promise<DiagnosticEventPage> {
    const parameters = new URLSearchParams({
      since: String(query.since ?? 0),
      limit: String(query.limit ?? 100),
    });
    if (query.type) parameters.set("type", query.type);
    if (query.conversationId?.trim()) {
      parameters.set("conversation_id", query.conversationId.trim());
    }
    const payload = await this.requestJson<{
      cursor: number;
      events: ApiRuntimeEvent[];
    }>(`/api/events/recent?${parameters.toString()}`, signal);
    return {
      cursor: payload.cursor,
      events: payload.events.map(convertEvent),
    };
  }

  async listLogs(
    query: DiagnosticLogQuery = {},
    signal?: AbortSignal,
  ): Promise<DiagnosticLogPage> {
    const parameters = new URLSearchParams({
      since: String(query.since ?? 0),
      limit: String(query.limit ?? 100),
    });
    if (query.level) parameters.set("level", query.level);
    if (query.search?.trim()) parameters.set("q", query.search.trim());
    const payload = await this.requestJson<{
      cursor: number;
      logs: ApiDiagnosticLog[];
    }>(`/api/logs/recent?${parameters.toString()}`, signal);
    return {
      cursor: payload.cursor,
      logs: payload.logs.map(convertLog),
    };
  }

  private async requestJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, { signal });
    if (!response.ok) throw new HttpResponseError(response.status);
    return await response.json() as T;
  }
}
