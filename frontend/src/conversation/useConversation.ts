import { computed, ref } from "vue";
import { errorMessage, requestJson } from "../api/http";
import type {
  ChatMessage,
  RuntimeEvent,
  SessionDetail,
  SessionSummary,
} from "../api/types";
import { postChatStream } from "../api/sse";

export interface Confirmation {
  id: string;
  sessionId: string;
  summary: string;
  status: "pending" | "submitting" | "resolved" | "expired" | "unknown";
  result: string;
}

export function createConversation() {
  const sessionId = ref<string | null>(null);
  const sessions = ref<SessionSummary[]>([]);
  const messages = ref<ChatMessage[]>([]);
  const events = ref<RuntimeEvent[]>([]);
  const confirmations = ref<Confirmation[]>([]);
  const busy = ref(false);
  const loading = ref(false);
  const error = ref("");
  const sessionsError = ref("");
  const sessionsLoading = ref(false);
  const phase = ref("");
  const pendingConfirmation = computed(
    () =>
      confirmations.value.find(
        (item) => item.status === "pending" || item.status === "submitting",
      ) ?? null,
  );
  let selectionRevision = 0;
  let listRevision = 0;
  let streamController: AbortController | null = null;
  let selectionController: AbortController | null = null;

  async function refreshSessions() {
    const revision = ++listRevision;
    sessionsLoading.value = true;
    try {
      const result = await requestJson<{ sessions: SessionSummary[] }>(
        "/api/sessions",
      );
      if (revision === listRevision) {
        sessions.value = result.sessions;
        sessionsError.value = "";
      }
    } catch (cause) {
      if (revision === listRevision) sessionsError.value = errorMessage(cause);
    } finally {
      if (revision === listRevision) sessionsLoading.value = false;
    }
  }

  async function selectSession(id: string) {
    if (busy.value) return false;
    const revision = ++selectionRevision;
    selectionController?.abort();
    selectionController = new AbortController();
    loading.value = true;
    error.value = "";
    try {
      const detail = await requestJson<SessionDetail>(
        `/api/sessions/${encodeURIComponent(id)}`,
        { signal: selectionController.signal },
      );
      if (revision !== selectionRevision) return false;
      sessionId.value = detail.session_id;
      messages.value = detail.messages;
      events.value = [];
      confirmations.value = [];
      phase.value = "";
      return true;
    } catch (cause) {
      if (revision === selectionRevision) error.value = errorMessage(cause);
      return false;
    } finally {
      if (revision === selectionRevision) loading.value = false;
    }
  }

  function newSession() {
    if (busy.value) return false;
    ++selectionRevision;
    selectionController?.abort();
    loading.value = false;
    sessionId.value = null;
    messages.value = [];
    events.value = [];
    confirmations.value = [];
    error.value = "";
    phase.value = "";
    return true;
  }

  async function deleteSession(id: string) {
    if (busy.value || loading.value) return false;
    loading.value = true;
    error.value = "";
    try {
      await requestJson(`/api/sessions/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (sessionId.value === id) newSession();
      await refreshSessions();
      return true;
    } catch (cause) {
      error.value = errorMessage(cause);
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function send(message: string) {
    const text = message.trim();
    if (!text || busy.value || loading.value) return false;
    busy.value = true;
    error.value = "";
    phase.value = "正在回应";
    events.value = [];
    confirmations.value = [];
    messages.value.push({ role: "user", content: text });
    const assistantIndex =
      messages.value.push({ role: "assistant", content: "" }) - 1;
    const controller = new AbortController();
    streamController = controller;
    let streamSession = sessionId.value;
    try {
      await postChatStream(
        streamSession,
        text,
        (event) => {
          if (event.type === "session") {
            if (
              !event.session_id ||
              (streamSession && event.session_id !== streamSession)
            )
              throw new Error("收到其他会话的响应，本轮已中断。");
            streamSession = event.session_id;
            sessionId.value = streamSession;
          } else if (
            event.session_id &&
            streamSession &&
            event.session_id !== streamSession
          ) {
            throw new Error("收到其他会话的事件，本轮已中断。");
          }
          if (event.type === "text_delta")
            messages.value[assistantIndex]!.content += event.text ?? "";
          else if (event.type === "confirmation") {
            if (
              typeof event.id === "string" &&
              event.id.trim() &&
              event.session_id === streamSession &&
              streamSession
            ) {
              if (!confirmations.value.some((item) => item.id === event.id))
                confirmations.value.push({
                  id: event.id,
                  sessionId: streamSession,
                  summary: event.summary ?? "此操作需要你的确认。",
                  status: "pending",
                  result: "",
                });
            } else
              events.value.push({
                type: "warning",
                message: event.summary || "操作没有可用的确认凭证，未执行。",
              });
          } else if (event.type === "turn_end")
            phase.value = "回复完成，正在处理后续反馈";
          else if (event.type === "error") {
            error.value = event.message || "本轮处理失败。";
            events.value.push(event);
          } else if (event.type !== "session" && event.type !== "done")
            events.value.push(event);
        },
        controller.signal,
      );
      phase.value = error.value ? "本轮发生错误" : "本轮已完成";
      return !error.value;
    } catch (cause) {
      error.value = controller.signal.aborted
        ? "本轮已停止。已收到的内容已保留。"
        : errorMessage(cause);
      phase.value = "本轮已中断";
      return false;
    } finally {
      confirmations.value.forEach((item) => {
        if (item.status === "pending") {
          item.status = "expired";
          item.result = "本轮已结束，确认已失效。";
        }
      });
      if (!messages.value[assistantIndex]?.content)
        messages.value.splice(assistantIndex, 1);
      streamController = null;
      busy.value = false;
      void refreshSessions();
    }
  }

  async function answerConfirmation(item: Confirmation, approved: boolean) {
    if (
      !busy.value ||
      item.status !== "pending" ||
      item.sessionId !== sessionId.value
    )
      return;
    item.status = "submitting";
    try {
      const result = await requestJson<{
        accepted: boolean;
        approved: boolean;
      }>(`/api/confirmations/${encodeURIComponent(item.id)}`, {
        method: "POST",
        body: JSON.stringify({ session_id: item.sessionId, approved }),
      });
      item.status = result.accepted ? "resolved" : "expired";
      item.result = result.accepted
        ? approved
          ? "已提交同意，正在等待实际执行结果。"
          : "已提交拒绝。"
        : "确认已失效或已处理，本次没有再次执行。";
    } catch (cause) {
      item.status = "unknown";
      item.result = `未能确认提交结果：${errorMessage(cause)}。为避免重复操作，不会自动重发。`;
    }
  }

  async function stop() {
    if (!busy.value) return;
    // Cancelling this POST closes its reader; the server reaps that exact turn
    // before releasing the session lock. A separate session-wide abort could
    // arrive late and accidentally interrupt a subsequent turn.
    streamController?.abort();
  }

  return {
    sessionId,
    sessions,
    messages,
    events,
    confirmations,
    busy,
    loading,
    error,
    sessionsError,
    sessionsLoading,
    phase,
    pendingConfirmation,
    refreshSessions,
    selectSession,
    newSession,
    deleteSession,
    send,
    answerConfirmation,
    stop,
  };
}

const conversation = createConversation();
export function useConversation() {
  return conversation;
}
