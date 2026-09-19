<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { errorMessage, requestJson } from "../api/http";
import type { LifeRecord, RecordKind } from "../api/types";
import {
  isDone,
  localTime,
  recordLabels,
  rules,
  statusLabel,
  toLocalInput,
} from "./recordModel";
const props = defineProps<{ kind: RecordKind }>();
const records = ref<LifeRecord[]>([]);
const query = ref("");
const loading = ref(false);
const busy = ref(false);
const notice = ref("");
const failed = ref(false);
const editing = ref<string | null>(null);
const deleting = ref("");
const draft = reactive({ title: "", detail: "", due: "" });
const operation = ref("");
const includeDone = ref(true);
let revision = 0;
let controller: AbortController | null = null;
let disposed = false;
const visible = computed(() =>
  includeDone.value ? records.value : records.value.filter((r) => !isDone(r)),
);
async function load() {
  const rev = ++revision;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  try {
    const data = await requestJson<{ records: LifeRecord[] }>(
      `/api/records/${props.kind}${query.value ? `?q=${encodeURIComponent(query.value)}` : ""}`,
      { signal: controller.signal },
    );
    if (rev === revision) records.value = data.records;
  } catch (e) {
    if (rev === revision && !disposed) {
      failed.value = true;
      notice.value = errorMessage(e);
    }
  } finally {
    if (rev === revision) loading.value = false;
  }
}
function edit(record?: LifeRecord) {
  editing.value = record?.id ?? "";
  deleting.value = "";
  draft.title = record?.title || "";
  draft.detail = record?.detail || "";
  draft.due = toLocalInput(record?.due_at);
}
async function mutate(path: string, method: string, body?: unknown) {
  if (busy.value) return false;
  busy.value = true;
  notice.value = "";
  failed.value = false;
  const kind = props.kind;
  try {
    const result = await requestJson<{ operation_id?: string }>(path, {
      method,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (disposed || kind !== props.kind) return false;
    operation.value = result.operation_id || "";
    notice.value = "已保存。";
    editing.value = null;
    deleting.value = "";
    await load();
    return true;
  } catch (e) {
    if (!disposed && kind === props.kind) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
    return false;
  } finally {
    if (!disposed) busy.value = false;
  }
}
function save() {
  if (!draft.title.trim()) {
    notice.value = "请填写标题。";
    failed.value = true;
    return;
  }
  return mutate(
    `/api/records/${props.kind}${editing.value ? `/${encodeURIComponent(editing.value)}` : ""}`,
    editing.value ? "PATCH" : "POST",
    {
      title: draft.title.trim(),
      detail: draft.detail,
      due_at: draft.due ? new Date(draft.due).toISOString() : null,
    },
  );
}
function toggle(record: LifeRecord) {
  return mutate(
    `/api/records/${props.kind}/${encodeURIComponent(record.id)}`,
    "PATCH",
    {
      status: isDone(record) ? rules[props.kind].open : rules[props.kind].done,
    },
  );
}
async function undo() {
  if (!operation.value || busy.value) return;
  const id = operation.value;
  if (await mutate(`/api/records/undo/${encodeURIComponent(id)}`, "POST")) {
    operation.value = "";
    notice.value = "已撤销上一步。";
  }
}
watch(
  () => props.kind,
  () => {
    records.value = [];
    query.value = "";
    editing.value = null;
    operation.value = "";
    notice.value = "";
    deleting.value = "";
    void load();
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  disposed = true;
  ++revision;
  controller?.abort();
});
</script>
<template>
  <section class="page-stack">
    <header class="page-heading">
      <p class="eyebrow">
        {{ kind === "memories" ? "值得记得的事" : "把生活，安排得从容一点" }}
      </p>
      <h1>{{ recordLabels[kind] }}</h1>
      <p class="muted">
        {{
          kind === "memories"
            ? "管理长期保留的信息，让记忆跟上你的变化。"
            : "每件小事，都有自己的位置。"
        }}
      </p>
    </header>
    <div class="records-toolbar">
      <form class="search" @submit.prevent="load">
        <label class="sr-only" for="record-query"
          >搜索{{ recordLabels[kind] }}</label
        ><input
          id="record-query"
          v-model="query"
          type="search"
          placeholder="查找标题或内容"
        /><button class="button" :disabled="loading" type="submit">搜索</button>
      </form>
      <div class="row-actions">
        <button class="button" :disabled="!operation || busy" @click="undo">
          撤销上一步</button
        ><button class="button primary" :disabled="busy" @click="edit()">
          新建{{ recordLabels[kind] }}
        </button>
      </div>
    </div>
    <label class="muted"
      ><input v-model="includeDone" type="checkbox" />
      显示已完成或失效的记录</label
    >
    <p
      v-if="notice"
      :role="failed ? 'alert' : 'status'"
      :class="['notice', { error: failed }]"
    >
      {{ notice }}
    </p>
    <form
      v-if="editing !== null"
      class="panel page-stack record-editor"
      @submit.prevent="save"
    >
      <h2>{{ editing ? "编辑" : "新建" }}{{ recordLabels[kind] }}</h2>
      <label class="field"
        >标题<input
          v-model="draft.title"
          required
          :disabled="busy"
          maxlength="1000"
      /></label>
      <label class="field"
        >内容<textarea v-model="draft.detail" rows="4" :disabled="busy" />
      </label>
      <label class="field"
        >时间（本地，可留空）<input
          v-model="draft.due"
          type="datetime-local"
          :disabled="busy"
      /></label>
      <div class="row-actions">
        <button class="button primary" type="submit" :disabled="busy">
          {{ busy ? "保存中…" : "保存" }}</button
        ><button
          class="button"
          type="button"
          :disabled="busy"
          @click="editing = null"
        >
          取消
        </button>
      </div>
    </form>
    <p v-if="loading" role="status" class="muted">正在读取…</p>
    <p v-else-if="!visible.length" class="panel empty-state">
      {{
        query ? "没有找到匹配的记录。" : "还没有记录，留下一件想记得的小事吧。"
      }}
    </p>
    <div v-else class="record-list">
      <article
        v-for="record in visible"
        :key="record.id"
        class="panel record-card"
        :data-record-id="record.id"
      >
        <div class="record-title">
          <h2>{{ record.title || "无标题" }}</h2>
          <span class="badge">{{ statusLabel(record.status) }}</span>
        </div>
        <p v-if="record.detail" class="record-detail">{{ record.detail }}</p>
        <p v-if="record.status.toLowerCase() === 'superseded'" class="notice">
          已被习惯 {{ record.meta?.superseded_by_skill || "规则" }} 替代。{{
            record.meta?.superseded_reason || ""
          }}
          {{
            record.meta?.superseded_at
              ? localTime(String(record.meta.superseded_at))
              : ""
          }}
        </p>
        <div class="record-footer">
          <span class="muted small"
            >{{ localTime(record.due_at || record.created_at)
            }}{{ !record.due_at ? "（创建）" : "" }}</span
          >
          <div class="row-actions">
            <button class="button" :disabled="busy" @click="edit(record)">
              编辑</button
            ><button class="button" :disabled="busy" @click="toggle(record)">
              {{
                isDone(record)
                  ? "恢复"
                  : kind === "notes"
                    ? "归档"
                    : kind === "memories"
                      ? "设为失效"
                      : "完成"
              }}</button
            ><button
              class="button danger"
              :disabled="busy"
              @click="deleting = record.id"
            >
              删除
            </button>
          </div>
        </div>
        <div v-if="deleting === record.id" class="notice delete-confirm">
          <span>删除“{{ record.title }}”？完成后可撤销上一步。</span>
          <div class="row-actions">
            <button
              class="button danger"
              :disabled="busy"
              @click="
                mutate(
                  `/api/records/${kind}/${encodeURIComponent(record.id)}`,
                  'DELETE',
                )
              "
            >
              确认删除</button
            ><button class="button" :disabled="busy" @click="deleting = ''">
              取消删除
            </button>
          </div>
        </div>
      </article>
    </div>
    <p v-if="kind === 'reminders'" class="muted small">
      这里管理提醒记录；当前版本暂不提供设备推送通知。
    </p>
  </section>
</template>
<style scoped>
.records-toolbar,
.record-footer,
.record-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.search {
  display: flex;
  gap: 8px;
  flex: 1;
  max-width: 440px;
}
.record-list {
  display: grid;
  gap: 14px;
}
.record-title {
  align-items: start;
  flex-wrap: nowrap;
}
.record-title h2 {
  margin: 0;
  overflow-wrap: anywhere;
}
.record-detail {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 12px 0 20px;
}
.record-footer {
  margin-top: 15px;
}
.record-editor {
  gap: 15px;
}
.record-editor h2 {
  margin: 0;
}
.delete-confirm {
  margin-top: 15px;
  display: grid;
  gap: 12px;
}
.record-card {
  min-width: 0;
}
@media (max-width: 700px) {
  .search {
    max-width: none;
    width: 100%;
    flex: auto;
  }
  .record-footer .button {
    padding: 5px 10px;
  }
  .record-footer {
    gap: 10px;
  }
}
</style>
