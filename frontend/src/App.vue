<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAppearance } from "./appearance/useAppearance";
import { useConversation } from "./conversation/useConversation";
const CalendarDrawer = defineAsyncComponent(
  () => import("./calendar/CalendarDrawer.vue"),
);
import NotificationBubbles from "./calendar/NotificationBubbles.vue";
import { calendarOpen, openCalendar } from "./calendar/calendarState";
const route = useRoute();
const router = useRouter();
const { theme } = useAppearance();
const {
  sessionId,
  sessions,
  sessionsLoading,
  sessionsError,
  error: conversationError,
  busy,
  pendingConfirmation,
  refreshSessions,
  selectSession,
  newSession,
} = useConversation();
const menuOpen = ref(false);
const isMobile = ref(false);
const pageHidden = ref(false);
let mobileQuery: MediaQueryList | undefined;
function syncViewport() {
  isMobile.value = mobileQuery?.matches ?? false;
  if (!isMobile.value) menuOpen.value = false;
}
function syncVisibility() {
  pageHidden.value = document.hidden;
}
const collapsed = ref(false);
const sessionOpenError = ref("");
let navigationRevision = 0;
const menuButton = ref<HTMLButtonElement>();
const drawer = ref<HTMLElement>();
const primary = [
  ["/conversation", "◯", "对话"],
  ["/settings/persona", "✥", "设置"],
];
const settings = [
  ["/settings/persona", "人格"],
  ["/settings/memory", "记忆"],
  ["/settings/skills", "已学会的方法"],
  ["/settings/tasks", "任务"],
  ["/settings/notes", "笔记"],
  ["/settings/providers", "模型"],
  ["/settings/appearance", "外观"],
  ["/settings/history", "对话历史"],
  ["/settings/diagnostics", "运行状态"],
];
const secondary = computed(() =>
  route.path.startsWith("/settings") ? settings : [],
);
function active(path: string) {
  return path.startsWith("/life")
    ? route.path.startsWith("/life")
    : path.startsWith("/settings")
      ? route.path.startsWith("/settings")
      : route.path === path;
}
async function closeMenu(restore = false) {
  menuOpen.value = false;
  if (restore) {
    await nextTick();
    menuButton.value?.focus();
  }
}
async function openMenu() {
  menuOpen.value = true;
  await nextTick();
  drawer.value?.querySelector<HTMLElement>("a,button")?.focus();
}
function trapFocus(event: KeyboardEvent) {
  if (!menuOpen.value || event.key !== "Tab") return;
  const controls = Array.from(
    drawer.value?.querySelectorAll<HTMLElement>("a,button:not(:disabled)") ||
      [],
  ).filter((el) => el.offsetParent !== null);
  const first = controls[0],
    last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
async function openSession(id: string) {
  if (busy.value) return;
  const revision = ++navigationRevision;
  sessionOpenError.value = "";
  const selected = await selectSession(id);
  if (revision !== navigationRevision) return;
  if (!selected) {
    sessionOpenError.value =
      conversationError.value || "会话暂时无法打开，请重试。";
    return;
  }
  await router.push("/conversation");
  closeMenu();
}
async function createSession() {
  if (busy.value) return;
  ++navigationRevision;
  sessionOpenError.value = "";
  newSession();
  await router.push("/conversation");
  closeMenu();
}
watch(
  () => route.fullPath,
  () => {
    ++navigationRevision;
    closeMenu();
    if (route.query.calendar) openCalendar();
  },
  { flush: "sync", immediate: true },
);
onMounted(() => {
  mobileQuery = window.matchMedia?.("(max-width: 700px)");
  syncViewport();
  syncVisibility();
  mobileQuery?.addEventListener("change", syncViewport);
  document.addEventListener("visibilitychange", syncVisibility);
  void refreshSessions();
});
onBeforeUnmount(() => {
  mobileQuery?.removeEventListener("change", syncViewport);
  document.removeEventListener("visibilitychange", syncVisibility);
});
</script>

<template>
  <div
    class="app-frame"
    :class="{ 'nav-collapsed': collapsed }"
    :data-page-hidden="pageHidden || undefined"
    @keydown.esc="closeMenu(true)"
  >
    <div v-if="theme.assets" class="theme-decoration" aria-hidden="true">
      <img class="theme-corner" :src="theme.assets.corner" alt="" /><img
        class="theme-motif"
        :src="theme.assets.motif"
        alt=""
      />
    </div>
    <header class="title-bar">
      <button
        ref="menuButton"
        class="button mobile-menu"
        aria-label="打开导航"
        :aria-expanded="menuOpen"
        @click="openMenu"
      >
        ☰</button
      ><RouterLink class="wordmark" to="/conversation"
        ><span class="brand-dot"></span>MellowDay</RouterLink
      ><span class="title-note">把日子，慢慢过好。</span
      ><RouterLink class="theme-link" to="/settings/appearance"
        >◉ <span>{{ theme.label }}</span></RouterLink
      >
    </header>
    <Transition name="shade">
      <button
        v-if="menuOpen"
        class="drawer-backdrop"
        aria-label="关闭导航"
        @click="closeMenu(true)"
      ></button>
    </Transition>
    <aside
      ref="drawer"
      class="sidebar"
      :class="{ 'is-open': menuOpen }"
      :inert="(isMobile && !menuOpen) || undefined"
      :aria-hidden="(isMobile && !menuOpen) || undefined"
      :role="menuOpen ? 'dialog' : undefined"
      :aria-modal="menuOpen || undefined"
      aria-label="主导航"
      @keydown="trapFocus"
    >
      <div class="sidebar-brand">
        <img v-if="theme.assets" :src="theme.assets.emblem" alt="" />
        <div v-else class="minimal-emblem">◯</div>
        <span class="brand-name">MellowDay</span>
        <p>慢慢过日子，也好好记得你。</p>
      </div>
      <nav class="primary-nav">
        <RouterLink
          v-for="[path, icon, label] in primary"
          :key="path"
          :to="path!"
          :class="{ selected: active(path!) }"
          :title="label"
          :aria-current="active(path!) ? 'page' : undefined"
          ><span class="nav-icon" aria-hidden="true">{{ icon }}</span
          ><span class="nav-label">{{ label }}</span></RouterLink
        >
        <button :aria-expanded="calendarOpen" @click="openCalendar()">
          <span class="nav-icon" aria-hidden="true">▦</span
          ><span class="nav-label">日历</span>
        </button>
      </nav>
      <section class="recent-sessions">
        <div class="recent-title">
          <span>最近对话</span
          ><button
            class="icon-button"
            :disabled="busy"
            aria-label="新建对话"
            @click="createSession"
          >
            ＋
          </button>
        </div>
        <p v-if="sessionsLoading" class="muted small" role="status">
          正在读取对话…
        </p>
        <p
          v-else-if="sessionsError || sessionOpenError"
          class="muted small"
          role="alert"
        >
          {{ sessionsError || sessionOpenError }}
        </p>
        <p v-else-if="!sessions.length" class="muted small">
          日常的片段，从这里开始。
        </p>
        <button
          v-for="session in sessions.slice(0, 8)"
          :key="session.session_id"
          class="session-link"
          :class="{ selected: session.session_id === sessionId }"
          :disabled="busy"
          @click="openSession(session.session_id)"
        >
          {{ session.title || "新的对话" }}</button
        ><RouterLink
          v-if="sessions.length"
          class="all-history"
          to="/settings/history"
          >查看全部 →</RouterLink
        >
      </section>
      <button
        class="collapse-nav"
        @click="collapsed = !collapsed"
        :aria-label="collapsed ? '展开导航' : '收起导航'"
      >
        {{ collapsed ? "»" : "« 收起导航" }}
      </button>
      <button class="button mobile-close" @click="closeMenu(true)">
        关闭导航
      </button>
    </aside>
    <main class="workspace" :inert="menuOpen || undefined">
      <nav v-if="secondary.length" class="secondary-nav" aria-label="页面分类">
        <RouterLink
          v-for="[path, label] in secondary"
          :key="path"
          :to="path!"
          :aria-current="route.path === path ? 'page' : undefined"
          >{{ label }}</RouterLink
        >
      </nav>
      <RouterLink
        v-if="busy && route.path !== '/conversation'"
        to="/conversation"
        class="activity-banner"
        role="status"
        >{{ pendingConfirmation ? "有一项操作等待你的确认" : "对话正在进行" }} ·
        返回对话 →</RouterLink
      >
      <RouterView v-slot="{ Component }">
        <div :key="route.path" class="route-page">
          <component :is="Component" />
        </div>
      </RouterView>
    </main>
    <CalendarDrawer v-if="calendarOpen" />
    <NotificationBubbles />
  </div>
</template>
