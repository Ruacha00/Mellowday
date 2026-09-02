import {
  HttpResponseError,
  type ConfirmationBinding,
  type ConfirmationDecision,
  type PendingConfirmation,
} from "./conversationApi";

export type ReminderDeliveryState =
  | "scheduled"
  | "delivering"
  | "delivered"
  | "failed"
  | "dismissed"
  | "cancelled";

export interface Reminder {
  id: string;
  message: string;
  dueAt: string;
  deliveryState: ReminderDeliveryState;
  taskId: string | null;
  conversationId: string;
  createdAt: number;
  updatedAt: number;
  deliveryAttemptedAt: number | null;
  deliveredAt: number | null;
  dismissedAt: number | null;
  cancelledAt: number | null;
  deliveryError: string | null;
}

export interface ReminderDraft {
  message: string;
  dueAt: string;
  taskId: string | null;
  conversationId: string;
}

export interface ReminderDeleteResult {
  ok: boolean;
  decision: ConfirmationDecision;
}

export interface ReminderService {
  listReminders(signal?: AbortSignal): Promise<Reminder[]>;
  getReminder(reminderId: string, signal?: AbortSignal): Promise<Reminder>;
  createReminder(
    draft: ReminderDraft,
    signal?: AbortSignal,
  ): Promise<Reminder>;
  updateReminder(
    reminderId: string,
    draft: ReminderDraft,
    signal?: AbortSignal,
  ): Promise<Reminder>;
  dismissReminder(reminderId: string, signal?: AbortSignal): Promise<Reminder>;
  cancelReminder(reminderId: string, signal?: AbortSignal): Promise<Reminder>;
  requestDeleteConfirmation(
    reminderId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation>;
  decideDelete(
    reminderId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<ReminderDeleteResult>;
}

interface ApiReminder {
  id: string;
  message: string;
  due_at: string;
  delivery_state: ReminderDeliveryState;
  task_id: string | null;
  conversation_id: string;
  created_at: number;
  updated_at: number;
  delivery_attempted_at: number | null;
  delivered_at: number | null;
  dismissed_at: number | null;
  cancelled_at: number | null;
  delivery_error: string | null;
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

function convertReminder(reminder: ApiReminder): Reminder {
  return {
    id: reminder.id,
    message: reminder.message,
    dueAt: reminder.due_at,
    deliveryState: reminder.delivery_state,
    taskId: reminder.task_id,
    conversationId: reminder.conversation_id,
    createdAt: reminder.created_at,
    updatedAt: reminder.updated_at,
    deliveryAttemptedAt: reminder.delivery_attempted_at,
    deliveredAt: reminder.delivered_at,
    dismissedAt: reminder.dismissed_at,
    cancelledAt: reminder.cancelled_at,
    deliveryError: reminder.delivery_error,
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

function toApiDraft(draft: ReminderDraft) {
  return {
    message: draft.message,
    due_at: draft.dueAt,
    task_id: draft.taskId,
    conversation_id: draft.conversationId,
  };
}

export class HttpReminderService implements ReminderService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listReminders(signal?: AbortSignal): Promise<Reminder[]> {
    const payload = await this.requestJson<{ reminders: ApiReminder[] }>(
      "/api/settings/reminders",
      { signal },
    );
    return payload.reminders.map(convertReminder);
  }

  async getReminder(
    reminderId: string,
    signal?: AbortSignal,
  ): Promise<Reminder> {
    const payload = await this.requestJson<{ reminder: ApiReminder }>(
      `/api/settings/reminders/${encodeURIComponent(reminderId)}`,
      { signal },
    );
    return convertReminder(payload.reminder);
  }

  async createReminder(
    draft: ReminderDraft,
    signal?: AbortSignal,
  ): Promise<Reminder> {
    const payload = await this.requestJson<{ reminder: ApiReminder }>(
      "/api/settings/reminders",
      this.jsonRequest("POST", toApiDraft(draft), signal),
    );
    return convertReminder(payload.reminder);
  }

  async updateReminder(
    reminderId: string,
    draft: ReminderDraft,
    signal?: AbortSignal,
  ): Promise<Reminder> {
    const payload = await this.requestJson<{ reminder: ApiReminder }>(
      `/api/settings/reminders/${encodeURIComponent(reminderId)}`,
      this.jsonRequest("PATCH", toApiDraft(draft), signal),
    );
    return convertReminder(payload.reminder);
  }

  dismissReminder(reminderId: string, signal?: AbortSignal): Promise<Reminder> {
    return this.runStateMutation(reminderId, "dismiss", signal);
  }

  cancelReminder(reminderId: string, signal?: AbortSignal): Promise<Reminder> {
    return this.runStateMutation(reminderId, "cancel", signal);
  }

  async requestDeleteConfirmation(
    reminderId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation> {
    const payload = await this.requestJson<{
      confirmation: ApiPendingConfirmation;
    }>(
      `/api/settings/reminders/${encodeURIComponent(reminderId)}/delete-confirmation`,
      { method: "POST", signal },
    );
    return convertConfirmation(payload.confirmation);
  }

  decideDelete(
    reminderId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<ReminderDeleteResult> {
    return this.requestJson<ReminderDeleteResult>(
      `/api/settings/reminders/${encodeURIComponent(reminderId)}`,
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

  private async runStateMutation(
    reminderId: string,
    operation: "dismiss" | "cancel",
    signal?: AbortSignal,
  ): Promise<Reminder> {
    const payload = await this.requestJson<{ reminder: ApiReminder }>(
      `/api/settings/reminders/${encodeURIComponent(reminderId)}/${operation}`,
      { method: "POST", signal },
    );
    return convertReminder(payload.reminder);
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
