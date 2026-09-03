import {
  HttpResponseError,
  type ConfirmationBinding,
  type ConfirmationDecision,
  type PendingConfirmation,
} from "./conversationApi";

export interface CalendarEvent {
  id: string;
  title: string;
  startAt: string;
  endAt: string | null;
  details: string | null;
  createdAt: number;
  updatedAt: number;
}

export interface CalendarEventDraft {
  title: string;
  startAt: string;
  endAt: string | null;
  details: string | null;
}

export interface CalendarEventResult {
  calendarEvent: CalendarEvent;
  conflicts: CalendarEvent[];
}

export interface CalendarEventCollection {
  calendarEvents: CalendarEvent[];
  conflicts: Record<string, CalendarEvent[]>;
}

export interface CalendarEventDeleteResult {
  ok: boolean;
  decision: ConfirmationDecision;
}

export interface CalendarEventService {
  listCalendarEvents(signal?: AbortSignal): Promise<CalendarEventCollection>;
  getCalendarEvent(
    eventId: string,
    signal?: AbortSignal,
  ): Promise<CalendarEventResult>;
  createCalendarEvent(
    draft: CalendarEventDraft,
    signal?: AbortSignal,
  ): Promise<CalendarEventResult>;
  updateCalendarEvent(
    eventId: string,
    draft: CalendarEventDraft,
    signal?: AbortSignal,
  ): Promise<CalendarEventResult>;
  requestDeleteConfirmation(
    eventId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation>;
  decideDelete(
    eventId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<CalendarEventDeleteResult>;
}

interface ApiCalendarEvent {
  id: string;
  title: string;
  start_at: string;
  end_at: string | null;
  details: string | null;
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

function convertCalendarEvent(event: ApiCalendarEvent): CalendarEvent {
  return {
    id: event.id,
    title: event.title,
    startAt: event.start_at,
    endAt: event.end_at,
    details: event.details,
    createdAt: event.created_at,
    updatedAt: event.updated_at,
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

function convertResult(payload: {
  calendar_event: ApiCalendarEvent;
  conflicts: ApiCalendarEvent[];
}): CalendarEventResult {
  return {
    calendarEvent: convertCalendarEvent(payload.calendar_event),
    conflicts: payload.conflicts.map(convertCalendarEvent),
  };
}

function toApiDraft(draft: CalendarEventDraft) {
  return {
    title: draft.title,
    start_at: draft.startAt,
    end_at: draft.endAt,
    details: draft.details,
  };
}

export class HttpCalendarEventService implements CalendarEventService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listCalendarEvents(
    signal?: AbortSignal,
  ): Promise<CalendarEventCollection> {
    const payload = await this.requestJson<{
      calendar_events: ApiCalendarEvent[];
      conflicts: Record<string, ApiCalendarEvent[]>;
    }>("/api/settings/calendar-events", { signal });
    return {
      calendarEvents: payload.calendar_events.map(convertCalendarEvent),
      conflicts: Object.fromEntries(
        Object.entries(payload.conflicts).map(([eventId, conflicts]) => [
          eventId,
          conflicts.map(convertCalendarEvent),
        ]),
      ),
    };
  }

  async getCalendarEvent(
    eventId: string,
    signal?: AbortSignal,
  ): Promise<CalendarEventResult> {
    return convertResult(await this.requestJson(
      `/api/settings/calendar-events/${encodeURIComponent(eventId)}`,
      { signal },
    ));
  }

  async createCalendarEvent(
    draft: CalendarEventDraft,
    signal?: AbortSignal,
  ): Promise<CalendarEventResult> {
    return convertResult(await this.requestJson(
      "/api/settings/calendar-events",
      this.jsonRequest("POST", toApiDraft(draft), signal),
    ));
  }

  async updateCalendarEvent(
    eventId: string,
    draft: CalendarEventDraft,
    signal?: AbortSignal,
  ): Promise<CalendarEventResult> {
    return convertResult(await this.requestJson(
      `/api/settings/calendar-events/${encodeURIComponent(eventId)}`,
      this.jsonRequest("PATCH", toApiDraft(draft), signal),
    ));
  }

  async requestDeleteConfirmation(
    eventId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation> {
    const payload = await this.requestJson<{
      confirmation: ApiPendingConfirmation;
    }>(
      `/api/settings/calendar-events/${encodeURIComponent(eventId)}/delete-confirmation`,
      { method: "POST", signal },
    );
    return convertConfirmation(payload.confirmation);
  }

  decideDelete(
    eventId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<CalendarEventDeleteResult> {
    return this.requestJson(
      `/api/settings/calendar-events/${encodeURIComponent(eventId)}`,
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

  private async requestJson<T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
