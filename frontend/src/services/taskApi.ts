import {
  HttpResponseError,
  type ConfirmationBinding,
  type ConfirmationDecision,
  type PendingConfirmation,
} from "./conversationApi";

export interface Task {
  id: string;
  title: string;
  details: string | null;
  completed: boolean;
  deadline: string | null;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
}

export interface TaskDraft {
  title: string;
  details: string | null;
  deadline: string | null;
}

export interface TaskDeleteResult {
  ok: boolean;
  decision: ConfirmationDecision;
}

export interface TaskService {
  listTasks(signal?: AbortSignal): Promise<Task[]>;
  createTask(draft: TaskDraft, signal?: AbortSignal): Promise<Task>;
  updateTask(
    taskId: string,
    draft: TaskDraft,
    signal?: AbortSignal,
  ): Promise<Task>;
  setCompleted(
    taskId: string,
    completed: boolean,
    signal?: AbortSignal,
  ): Promise<Task>;
  requestDeleteConfirmation(
    taskId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation>;
  decideDelete(
    taskId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<TaskDeleteResult>;
}

interface ApiTask {
  id: string;
  title: string;
  details: string | null;
  completed: boolean;
  deadline: string | null;
  created_at: number;
  updated_at: number;
  completed_at: number | null;
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

function convertTask(task: ApiTask): Task {
  return {
    id: task.id,
    title: task.title,
    details: task.details,
    completed: task.completed,
    deadline: task.deadline,
    createdAt: task.created_at,
    updatedAt: task.updated_at,
    completedAt: task.completed_at,
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

export class HttpTaskService implements TaskService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listTasks(signal?: AbortSignal): Promise<Task[]> {
    const payload = await this.requestJson<{ tasks: ApiTask[] }>(
      "/api/settings/tasks",
      { signal },
    );
    return payload.tasks.map(convertTask);
  }

  async createTask(draft: TaskDraft, signal?: AbortSignal): Promise<Task> {
    const payload = await this.requestJson<{ task: ApiTask }>(
      "/api/settings/tasks",
      this.jsonRequest("POST", draft, signal),
    );
    return convertTask(payload.task);
  }

  async updateTask(
    taskId: string,
    draft: TaskDraft,
    signal?: AbortSignal,
  ): Promise<Task> {
    const payload = await this.requestJson<{ task: ApiTask }>(
      `/api/settings/tasks/${encodeURIComponent(taskId)}`,
      this.jsonRequest("PATCH", draft, signal),
    );
    return convertTask(payload.task);
  }

  async setCompleted(
    taskId: string,
    completed: boolean,
    signal?: AbortSignal,
  ): Promise<Task> {
    const operation = completed ? "complete" : "reopen";
    const payload = await this.requestJson<{ task: ApiTask }>(
      `/api/settings/tasks/${encodeURIComponent(taskId)}/${operation}`,
      { method: "POST", signal },
    );
    return convertTask(payload.task);
  }

  async requestDeleteConfirmation(
    taskId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation> {
    const payload = await this.requestJson<{
      confirmation: ApiPendingConfirmation;
    }>(
      `/api/settings/tasks/${encodeURIComponent(taskId)}/delete-confirmation`,
      { method: "POST", signal },
    );
    return convertConfirmation(payload.confirmation);
  }

  async decideDelete(
    taskId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<TaskDeleteResult> {
    return this.requestJson<TaskDeleteResult>(
      `/api/settings/tasks/${encodeURIComponent(taskId)}`,
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
