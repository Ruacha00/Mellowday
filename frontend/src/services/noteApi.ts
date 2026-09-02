import {
  HttpResponseError,
  type ConfirmationBinding,
  type ConfirmationDecision,
  type PendingConfirmation,
} from "./conversationApi";

export interface Note {
  id: string;
  title: string | null;
  content: string;
  createdAt: number;
  updatedAt: number;
}

export interface NoteDraft {
  title: string | null;
  content: string;
}

export interface NoteDeleteResult {
  ok: boolean;
  decision: ConfirmationDecision;
}

export interface NoteService {
  listNotes(query?: string, signal?: AbortSignal): Promise<Note[]>;
  getNote(noteId: string, signal?: AbortSignal): Promise<Note>;
  createNote(draft: NoteDraft, signal?: AbortSignal): Promise<Note>;
  updateNote(
    noteId: string,
    draft: NoteDraft,
    signal?: AbortSignal,
  ): Promise<Note>;
  requestDeleteConfirmation(
    noteId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation>;
  decideDelete(
    noteId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<NoteDeleteResult>;
}

interface ApiNote {
  id: string;
  title: string | null;
  content: string;
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

function convertNote(note: ApiNote): Note {
  return {
    id: note.id,
    title: note.title,
    content: note.content,
    createdAt: note.created_at,
    updatedAt: note.updated_at,
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

export class HttpNoteService implements NoteService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async listNotes(query = "", signal?: AbortSignal): Promise<Note[]> {
    const search = query.trim();
    const path = search.length === 0
      ? "/api/settings/notes"
      : `/api/settings/notes?q=${encodeURIComponent(search)}`;
    const payload = await this.requestJson<{ notes: ApiNote[] }>(path, {
      signal,
    });
    return payload.notes.map(convertNote);
  }

  async getNote(noteId: string, signal?: AbortSignal): Promise<Note> {
    const payload = await this.requestJson<{ note: ApiNote }>(
      `/api/settings/notes/${encodeURIComponent(noteId)}`,
      { signal },
    );
    return convertNote(payload.note);
  }

  async createNote(
    draft: NoteDraft,
    signal?: AbortSignal,
  ): Promise<Note> {
    const payload = await this.requestJson<{ note: ApiNote }>(
      "/api/settings/notes",
      this.jsonRequest("POST", draft, signal),
    );
    return convertNote(payload.note);
  }

  async updateNote(
    noteId: string,
    draft: NoteDraft,
    signal?: AbortSignal,
  ): Promise<Note> {
    const payload = await this.requestJson<{ note: ApiNote }>(
      `/api/settings/notes/${encodeURIComponent(noteId)}`,
      this.jsonRequest("PATCH", draft, signal),
    );
    return convertNote(payload.note);
  }

  async requestDeleteConfirmation(
    noteId: string,
    signal?: AbortSignal,
  ): Promise<PendingConfirmation> {
    const payload = await this.requestJson<{
      confirmation: ApiPendingConfirmation;
    }>(
      `/api/settings/notes/${encodeURIComponent(noteId)}/delete-confirmation`,
      { method: "POST", signal },
    );
    return convertConfirmation(payload.confirmation);
  }

  decideDelete(
    noteId: string,
    confirmation: PendingConfirmation,
    decision: ConfirmationDecision,
    signal?: AbortSignal,
  ): Promise<NoteDeleteResult> {
    return this.requestJson<NoteDeleteResult>(
      `/api/settings/notes/${encodeURIComponent(noteId)}`,
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
