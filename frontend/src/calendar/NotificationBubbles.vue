<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import { useRouter } from "vue-router";
import { requestJson, errorMessage } from "../api/http";
import { useConversation } from "../conversation/useConversation";
import { openCalendar, type Notification } from "./calendarState";
const notifications = ref<Notification[]>([]),
  error = ref(""),
  working = ref("");
const { selectSession, busy } = useConversation();
const router = useRouter();
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let loading = false;
async function refresh() {
  if (loading) return;
  loading = true;
  try {
    const data = await requestJson<{ notifications: Notification[] }>(
      "/api/calendar/notifications",
    );
    if (!disposed) {
      notifications.value = data.notifications.filter((n) => !n.read);
      error.value = "";
    }
  } catch (e) {
    if (!disposed) error.value = errorMessage(e);
  } finally {
    loading = false;
  }
}
async function poll() {
  await refresh();
  if (!disposed) timer = setTimeout(poll, 30000);
}
async function read(item: Notification) {
  working.value = item.id;
  try {
    await requestJson(
      `/api/calendar/notifications/${encodeURIComponent(item.id)}/read`,
      { method: "POST" },
    );
    notifications.value = notifications.value.filter((n) => n.id !== item.id);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    working.value = "";
  }
}
async function open(item: Notification) {
  if (item.kind === "report" && item.session_id) {
    if (busy.value) {
      error.value = "当前回复结束后即可打开汇报。";
      return;
    }
    if (!(await selectSession(item.session_id))) {
      error.value = "接收对话暂时无法打开，消息仍保留为未读。";
      return;
    }
    await router.push("/conversation");
  } else
    openCalendar(
      item.event_id || item.event_ids?.[0],
      item.occurrence_start || item.scheduled_at,
    );
  await read(item);
}
function focus() {
  void refresh();
}
onMounted(() => {
  void poll();
  window.addEventListener("focus", focus);
});
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(timer);
  window.removeEventListener("focus", focus);
});
</script>
<template>
  <section class="notification-stack" aria-label="日程消息" aria-live="polite">
    <details v-if="error" class="notification-error">
      <summary>日程消息暂不可用</summary>
      <p>{{ error }}</p>
      <button class="button" @click="refresh">重试</button>
    </details>
    <article
      v-for="item in notifications.slice(0, 3)"
      :key="item.id"
      class="notification-bubble"
    >
      <button
        class="notification-body"
        :disabled="working === item.id"
        @click="open(item)"
      >
        <span class="eyebrow">{{
          item.kind === "report" ? "定时汇报" : "日程提醒"
        }}</span
        ><strong>{{ item.title }}</strong
        ><span>{{ item.body }}</span></button
      ><button
        class="icon-button"
        :disabled="working === item.id"
        aria-label="标记已读"
        @click="read(item)"
      >
        ✕
      </button>
    </article>
    <p v-if="notifications.length > 3" class="notification-more">
      还有 {{ notifications.length - 3 }} 条未读，处理后继续显示
    </p>
  </section>
</template>
