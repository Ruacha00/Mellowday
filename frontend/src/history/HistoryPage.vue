<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import type { TraceEntry } from "../api/types";
import { useConversation } from "../conversation/useConversation";
import MarkdownContent from "../conversation/MarkdownContent.vue";
import { createHistory } from "./useHistory";
import ToolResult from "./ToolResult.vue";

const router = useRouter();
const {
  sessions,
  sessionsError,
  sessionsLoading,
  busy,
  loading: conversationLoading,
  error: conversationError,
  refreshSessions,
  selectSession,
  deleteSession,
} = useConversation();
const { selectedId, detail, loading, error, load, clear } = createHistory();
const tab = ref<"messages" | "trace">("messages");
const filter = ref("");
const deleteTarget = ref("");
const feedback = ref("");
const filteredSessions = computed(() =>
  sessions.value.filter((item) =>
    item.title.toLocaleLowerCase().includes(filter.value.toLocaleLowerCase()),
  ),
);
const traceRows = computed(() =>
  (detail.value?.trace ?? []).map((entry, index) => ({
    raw: entry,
    shown: detail.value?.trace_display?.[index] ?? entry,
    index,
  })),
);
function label(entry: TraceEntry) {
  const labels: Record<string, string> = {
    user: "你",
    assistant: "MellowDay",
    message: "回复片段",
    tool_call: "调用工具",
    tool_result: "工具结果",
    error: "错误",
  };
  return `${labels[entry.type] ?? "执行记录"}${entry.name ? ` · ${entry.name}` : ""}${entry.turn != null ? ` · 第 ${entry.turn} 轮` : ""}`;
}
function content(entry: TraceEntry) {
  const value =
    entry.text ??
    entry.arguments ??
    entry.result ??
    entry.message ??
    entry.content ??
    "";
  const result =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return result.length > 12000
    ? `${result.slice(0, 12000)}\n…预览已折叠。`
    : result;
}
async function continueSession() {
  if (!selectedId.value || busy.value) return;
  if (await selectSession(selectedId.value)) await router.push("/conversation");
}
async function remove() {
  const id = deleteTarget.value;
  if (!id || busy.value) return;
  if (await deleteSession(id)) {
    if (selectedId.value === id) clear();
    deleteTarget.value = "";
    feedback.value = "会话及其执行记录已删除。";
  }
}
onMounted(() => {
  void refreshSessions();
});
onBeforeUnmount(clear);
</script>

<template>
  <section class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">回到聊过的那些时刻</p>
        <h1>会话历史</h1>
        <p class="muted">对话内容与原始执行记录都保留在这里。</p>
      </div>
      <button class="button" @click="refreshSessions">刷新</button>
    </header>
    <p
      v-if="sessionsError || error || conversationError"
      role="alert"
      class="notice error"
    >
      {{ sessionsError || error || conversationError }}
    </p>
    <p v-if="feedback" role="status" class="notice">{{ feedback }}</p>
    <p v-if="busy" role="status" class="notice">
      当前对话仍在进行，完成或停止后可以切换、继续或删除会话。
    </p>
    <div class="history-layout">
      <aside class="panel history-list" aria-label="历史会话列表">
        <label class="field"
          >查找会话<input
            v-model="filter"
            type="search"
            placeholder="按标题查找"
        /></label>
        <p v-if="sessionsLoading" role="status" class="muted">
          正在读取会话列表…
        </p>
        <p v-else-if="!sessions.length" class="empty-state">还没有历史会话。</p>
        <p v-else-if="!filteredSessions.length" class="empty-state">
          没有匹配的会话。
        </p>
        <button
          v-for="item in filteredSessions"
          :key="item.session_id"
          :class="[
            'session-item',
            { selected: selectedId === item.session_id },
          ]"
          :aria-pressed="selectedId === item.session_id"
          :disabled="busy"
          @click="
            deleteTarget = '';
            feedback = '';
            load(item.session_id);
          "
        >
          <strong>{{ item.title || "未命名会话" }}</strong
          ><span class="muted">{{ item.messages }} 条消息</span>
        </button>
      </aside>
      <div class="page-stack history-detail">
        <p v-if="loading" class="panel" role="status">正在读取会话…</p>
        <div v-else-if="!detail" class="panel empty-state">
          选择一段会话，查看当时的对话与执行过程。
        </div>
        <template v-else>
          <div class="panel history-toolbar">
            <div class="row-actions" aria-label="历史视图">
              <button
                class="button"
                :class="{ primary: tab === 'messages' }"
                :aria-pressed="tab === 'messages'"
                @click="tab = 'messages'"
              >
                对话消息</button
              ><button
                class="button"
                :class="{ primary: tab === 'trace' }"
                :aria-pressed="tab === 'trace'"
                @click="tab = 'trace'"
              >
                原始执行过程
              </button>
            </div>
            <div class="row-actions">
              <button
                class="button"
                :disabled="busy || conversationLoading"
                @click="continueSession"
              >
                继续这段对话</button
              ><button
                class="button danger"
                :disabled="busy || conversationLoading"
                @click="deleteTarget = selectedId"
              >
                删除会话
              </button>
            </div>
          </div>
          <div v-if="deleteTarget" class="panel" role="alert">
            <p>删除后，该会话、执行记录和工具原文都将被清除。</p>
            <div class="row-actions">
              <button
                class="button danger"
                :disabled="busy || conversationLoading"
                @click="remove"
              >
                确认删除</button
              ><button class="button" @click="deleteTarget = ''">取消</button>
            </div>
          </div>
          <template v-if="tab === 'messages'">
            <p v-if="!detail.messages.length" class="panel empty-state">
              这段会话还没有消息。
            </p>
            <article
              v-for="(message, index) in detail.messages"
              :key="index"
              class="panel history-message"
            >
              <span class="muted">{{
                message.role === "user" ? "你" : "MellowDay"
              }}</span
              ><MarkdownContent :content="message.content" />
            </article>
          </template>
          <template v-else>
            <p class="muted">
              这里保留消息片段、工具调用和最终回复；同一轮的片段与完整回复可能同时出现。
            </p>
            <p v-if="!traceRows.length" class="panel empty-state">
              这个会话没有原始执行记录，可以在“对话消息”中阅读已有内容。
            </p>
            <details
              v-for="row in traceRows"
              :key="`${detail.session_id}-${row.index}`"
              class="panel trace-row"
              :open="row.raw.type === 'error'"
            >
              <summary>{{ label(row.raw) }}</summary>
              <pre>{{ content(row.shown) }}</pre>
              <ToolResult
                v-if="
                  row.raw.type === 'tool_result' &&
                  typeof row.raw.ref === 'string' &&
                  row.raw.ref
                "
                :key="`${detail.session_id}-${row.raw.ref}`"
                :session-id="detail.session_id"
                :artifact-ref="row.raw.ref"
              />
              <p v-else-if="row.raw.truncated" class="muted">
                没有可用的结构化引用，无法读取完整原文。
              </p>
            </details>
          </template>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.history-layout {
  display: grid;
  grid-template-columns: minmax(220px, 290px) minmax(0, 1fr);
  gap: 1.5rem;
  align-items: start;
}
.history-list {
  display: grid;
  gap: 0.65rem;
  max-height: 76vh;
  overflow-y: auto;
}
.session-item {
  display: grid;
  gap: 0.4rem;
  padding: 0.9rem;
  text-align: left;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  color: var(--ink);
  font: inherit;
  cursor: pointer;
  overflow-wrap: anywhere;
}
.session-item:hover,
.session-item.selected {
  border-color: var(--border);
  background: var(--bg);
}
.session-item.selected {
  border-color: var(--accent);
}
.session-item:disabled {
  cursor: default;
  opacity: 0.55;
}
.session-item .muted {
  font-size: 0.8rem;
}
.history-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  justify-content: space-between;
}
.history-message > .muted {
  display: block;
  margin-bottom: 0.75rem;
  font-size: 0.85rem;
}
.trace-row summary {
  cursor: pointer;
  overflow-wrap: anywhere;
}
.trace-row pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 480px;
  overflow-y: auto;
  font: inherit;
  font-size: 0.9rem;
  line-height: 1.6;
}
@media (max-width: 850px) {
  .history-layout {
    grid-template-columns: 1fr;
  }
  .history-list {
    max-height: 280px;
  }
}
</style>
