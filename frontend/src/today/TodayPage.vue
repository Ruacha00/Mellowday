<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import type { LifeRecord, RecordKind } from "../api/types";
import { errorMessage, requestJson } from "../api/http";
import { localTime, recordLabels, todayRecords } from "../records/recordModel";
const records = ref<LifeRecord[]>([]);
const loading = ref(true);
const error = ref("");
const now = ref(new Date());
const kinds: RecordKind[] = ["todos", "calendar", "reminders"];
const links = {
  todos: "/life/tasks",
  calendar: "/life/calendar",
  reminders: "/life/reminders",
};
const grouped = computed(() =>
  kinds.map((kind) => ({
    kind,
    rows: todayRecords(
      records.value.filter((r) => r.kind === kind),
      now.value,
    ),
  })),
);
const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
let controller: AbortController;
let timer: ReturnType<typeof setInterval>;
let revision = 0;
async function refresh() {
  const rev = ++revision;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  now.value = new Date();
  try {
    const all = await Promise.all(
      kinds.map((kind) =>
        requestJson<{ records: LifeRecord[] }>(`/api/records/${kind}`, {
          signal: controller.signal,
        }),
      ),
    );
    if (rev === revision) records.value = all.flatMap((x) => x.records);
  } catch (e) {
    if (rev === revision) error.value = errorMessage(e);
  } finally {
    if (rev === revision) loading.value = false;
  }
}
onMounted(() => {
  void refresh();
  timer = setInterval(() => {
    now.value = new Date();
  }, 60000);
});
onBeforeUnmount(() => {
  ++revision;
  controller?.abort();
  clearInterval(timer);
});
</script>
<template>
  <section class="page-stack">
    <header class="page-heading">
      <p class="eyebrow">
        {{
          now.toLocaleDateString("zh-CN", {
            month: "long",
            day: "numeric",
            weekday: "long",
          })
        }}
      </p>
      <h1>今天，慢慢来。</h1>
      <p class="muted">从已经安排的小事开始，给自己留一点空白。</p>
    </header>
    <div class="row-actions">
      <span class="muted small">按 {{ timezone }} 当日时间展示未完成记录</span
      ><button class="button" :disabled="loading" @click="refresh">刷新</button>
    </div>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <p v-if="loading" role="status">正在整理今天的记录…</p>
    <template v-else
      ><section v-for="group in grouped" :key="group.kind" class="panel">
        <div class="today-title">
          <h2>
            {{ recordLabels[group.kind] }}
            <span class="badge">{{ group.rows.length }}</span>
          </h2>
          <RouterLink :to="links[group.kind as keyof typeof links]"
            >查看全部 →</RouterLink
          >
        </div>
        <p v-if="!group.rows.length" class="muted">
          今天还没有安排{{ recordLabels[group.kind] }}。
        </p>
        <article v-for="row in group.rows" :key="row.id" class="today-row">
          <time class="muted">{{ localTime(row.due_at) }}</time
          ><strong>{{ row.title }}</strong>
          <p v-if="row.detail" class="muted">{{ row.detail }}</p>
        </article>
      </section></template
    >
  </section>
</template>
<style scoped>
.today-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.today-title a {
  font-size: 0.8rem;
}
.today-row {
  border-top: 1px solid var(--line);
  padding: 13px 0;
  display: grid;
  grid-template-columns: 170px 1fr;
  gap: 4px 18px;
  overflow-wrap: anywhere;
}
.today-row p {
  grid-column: 2;
  margin: 0;
}
.today-row time {
  font-size: 0.8rem;
}
@media (max-width: 700px) {
  .today-row {
    grid-template-columns: 1fr;
  }
  .today-row p {
    grid-column: 1;
  }
}
</style>
