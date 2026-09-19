export type RecordKind =
  | "todos"
  | "calendar"
  | "reminders"
  | "notes"
  | "memories";
export interface LifeRecord {
  id: string;
  kind: RecordKind;
  title: string;
  detail: string;
  status: string;
  due_at: string | null;
  due_at_local?: string | null;
  created_at: string;
  updated_at: string;
  source?: string;
  meta: Record<string, unknown>;
  operation_id?: string;
}
export interface SessionSummary {
  session_id: string;
  title: string;
  messages: number;
  updated_at?: number;
  active?: boolean;
}
export interface ChatMessage {
  role: string;
  content: string;
  ts?: number;
}
export interface TraceEntry {
  type: string;
  turn?: number;
  name?: string;
  text?: string;
  content?: string;
  arguments?: unknown;
  result?: unknown;
  message?: string;
  ref?: string;
  chars?: number;
  preview?: string;
  truncated?: boolean;
  [key: string]: unknown;
}
export interface SessionDetail {
  session_id: string;
  messages: ChatMessage[];
  trace: TraceEntry[];
  trace_display: TraceEntry[];
  active: boolean;
}
export interface RuntimeEvent {
  type: string;
  session_id?: string;
  text?: string;
  id?: string;
  summary?: string;
  name?: string;
  message?: string;
  [key: string]: unknown;
}
export interface ModelConfig {
  api_base: string;
  model: string;
  thinking: boolean;
  max_turns: number | null;
  configured: boolean;
  api_key_hint: string;
}
