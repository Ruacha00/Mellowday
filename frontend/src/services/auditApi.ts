import { HttpResponseError, type RuntimeEvent } from "./conversationApi";

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

interface ApiAuditEvent {
  sequence: number;
  type: string;
  occurred_at: number;
  conversation_id: string | null;
  details: Record<string, unknown>;
}

export interface AuditService {
  listRecords(signal?: AbortSignal): Promise<RuntimeEvent[]>;
}

export class HttpAuditService implements AuditService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(globalThis),
    private readonly basePath = "",
  ) {}

  async listRecords(signal?: AbortSignal): Promise<RuntimeEvent[]> {
    const response = await this.fetchRequest(
      `${this.basePath}/api/settings/audit`,
      { signal },
    );
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    const payload = (await response.json()) as { events: ApiAuditEvent[] };
    return payload.events.map((event) => ({
      sequence: event.sequence,
      type: event.type,
      occurredAt: event.occurred_at,
      conversationId: event.conversation_id,
      details: event.details,
    }));
  }
}
