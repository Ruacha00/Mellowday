<script setup lang="ts">
import { computed, ref } from "vue";
import { useConversation } from "./useConversation";
import MarkdownContent from "./MarkdownContent.vue";
import EventFeed from "./EventFeed.vue";

const {
  sessionId,
  messages,
  events,
  confirmations,
  busy,
  loading,
  error,
  phase,
  newSession,
  send,
  stop,
  answerConfirmation,
} = useConversation();
const draft = ref("");
const composing = ref(false);
const canSend = computed(
  () => draft.value.trim().length > 0 && !busy.value && !loading.value,
);
async function submit() {
  if (!canSend.value || composing.value) return;
  const submitted = draft.value;
  if (await send(submitted)) {
    if (draft.value === submitted) draft.value = "";
  }
}
function onKeydown(event: KeyboardEvent) {
  if (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    !composing.value &&
    event.keyCode !== 229
  ) {
    event.preventDefault();
    void submit();
  }
}
</script>

<template>
  <section class="page-stack conversation-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">留一点时间给自己</p>
        <h1>与 MellowDay 聊聊</h1>
        <p class="muted">把想法说出来，一起整理今天的小事。</p>
      </div>
      <button class="button" :disabled="busy || loading" @click="newSession">
        新对话
      </button>
    </header>
    <p v-if="loading" role="status" class="notice">正在载入会话…</p>
    <div v-if="!messages.length && !loading" class="panel conversation-welcome">
      <span class="welcome-spark" aria-hidden="true">✦</span>
      <h2>此刻，想从哪里开始？</h2>
      <p class="muted">整理待办、记下一段心情，或只是轻松聊一会儿。</p>
      <div class="suggestions">
        <button
          v-for="suggestion in [
            '帮我梳理今天的待办',
            '我想记下一件小事',
            '今天有点累，陪我聊聊',
          ]"
          :key="suggestion"
          class="button"
          @click="draft = suggestion"
        >
          {{ suggestion }}
        </button>
      </div>
    </div>
    <div
      class="message-list"
      aria-label="对话消息"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <article
        v-for="(message, index) in messages"
        :key="index"
        :class="['message', { 'message-user': message.role === 'user' }]"
      >
        <span class="message-author">{{
          message.role === "user" ? "你" : "MellowDay"
        }}</span>
        <MarkdownContent v-if="message.content" :content="message.content" />
        <p v-else class="muted">正在想一想…</p>
      </article>
    </div>
    <EventFeed :events="events" />
    <section
      v-for="item in confirmations"
      :key="item.id"
      class="panel confirmation"
      aria-label="操作确认"
    >
      <h2>需要你的确认</h2>
      <pre>{{ item.summary }}</pre>
      <div
        v-if="item.status === 'pending' || item.status === 'submitting'"
        class="row-actions"
      >
        <button
          class="button primary"
          :disabled="item.status !== 'pending' || !busy"
          @click="answerConfirmation(item, true)"
        >
          同意本次操作
        </button>
        <button
          class="button"
          :disabled="item.status !== 'pending' || !busy"
          @click="answerConfirmation(item, false)"
        >
          拒绝
        </button>
        <span v-if="item.status === 'submitting'" role="status">正在提交…</span>
      </div>
      <p v-if="item.result" role="status">{{ item.result }}</p>
    </section>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <form class="panel composer" @submit.prevent="submit">
      <label class="sr-only" for="message-draft">想说的话</label>
      <textarea
        id="message-draft"
        v-model="draft"
        rows="3"
        placeholder="说说你的想法…"
        :disabled="busy || loading"
        @compositionstart="composing = true"
        @compositionend="composing = false"
        @keydown="onKeydown"
      />
      <div class="composer-actions">
        <span class="muted" role="status">{{
          busy ? phase : "Enter 发送 · Shift + Enter 换行"
        }}</span>
        <button v-if="busy" type="button" class="button danger" @click="stop">
          停止
        </button>
        <button
          v-else
          class="button primary"
          :disabled="!canSend"
          type="submit"
        >
          发送
        </button>
      </div>
    </form>
    <p
      v-if="sessionId && !busy && phase"
      class="muted turn-status"
      role="status"
    >
      {{ phase }}
    </p>
  </section>
</template>

<style scoped>
.conversation-page {
  max-width: 920px;
  margin-inline: auto;
}
.conversation-welcome {
  text-align: center;
  padding: 2.8rem 1.6rem;
}
.welcome-spark {
  display: inline-grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 20px;
  color: var(--accent-strong);
  background: var(--bg);
  font-size: 2rem;
}
.suggestions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 1.5rem;
}
.message-list {
  display: grid;
  gap: 1.2rem;
}
.message {
  padding: 1.3rem 1.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px 22px 22px;
  max-width: 90%;
}
.message-user {
  margin-left: auto;
  background: var(--surface-strong);
  border-radius: 22px 6px 22px 22px;
  min-width: min(280px, 85%);
}
.message-author {
  display: block;
  font-size: 0.78rem;
  color: var(--ink-muted);
  font-weight: 600;
  margin-bottom: 0.6rem;
}
.confirmation {
  border: 2px solid var(--accent);
}
.confirmation h2 {
  font-size: 1.05rem;
}
.confirmation pre {
  font: inherit;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 420px;
  overflow-y: auto;
}
.composer {
  padding: 1rem;
  position: sticky;
  bottom: 1rem;
}
.composer textarea {
  width: 100%;
  resize: vertical;
  border: 0;
  background: transparent;
  color: var(--ink);
  font: inherit;
  line-height: 1.6;
  padding: 0.5rem;
  min-height: 90px;
}
.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}
.composer-actions .muted {
  font-size: 0.8rem;
}
.turn-status {
  margin-top: 0;
  text-align: center;
  font-size: 0.85rem;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  clip-path: inset(50%);
  overflow: hidden;
}
@media (max-width: 600px) {
  .message {
    max-width: 96%;
    padding: 1rem;
  }
  .composer {
    bottom: 0.4rem;
  }
}
</style>
