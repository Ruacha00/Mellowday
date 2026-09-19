<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { errorMessage, requestJson } from "../api/http";
interface Skill {
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  when_to_use?: string;
  body?: string;
  notes?: string;
  source?: string;
  updated_at?: string;
}
interface Version {
  version: string;
  current?: boolean;
  updated_at?: string;
}
const skills = ref<Skill[]>([]);
const selected = ref<Skill | null>(null);
const versions = ref<Version[]>([]);
const historical = ref<Skill | null>(null);
const loading = ref(false);
const listLoading = ref(false);
const busy = ref(false);
const editing = ref(false);
const notice = ref("");
const failed = ref(false);
const restoreTarget = ref("");
const draft = reactive({
  description: "",
  when_to_use: "",
  instructions: "",
  note: "",
});
let revision = 0;
let listRevision = 0;
let disposed = false;
const endpoint = (name: string) => `/api/skills/${encodeURIComponent(name)}`;
async function list() {
  const rev = ++listRevision;
  listLoading.value = true;
  try {
    const data = await requestJson<{ skills: Skill[] }>("/api/skills");
    if (!disposed && rev === listRevision) skills.value = data.skills;
  } catch (e) {
    if (!disposed && rev === listRevision) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
  } finally {
    if (!disposed && rev === listRevision) listLoading.value = false;
  }
}
async function select(name: string, refresh = false) {
  if (busy.value && !refresh) return;
  const rev = ++revision;
  loading.value = true;
  selected.value = null;
  editing.value = false;
  historical.value = null;
  restoreTarget.value = "";
  notice.value = "";
  failed.value = false;
  try {
    const [skill, data] = await Promise.all([
      requestJson<Skill>(endpoint(name)),
      requestJson<{ versions: Version[] }>(`${endpoint(name)}/versions`),
    ]);
    if (rev === revision && !disposed) {
      selected.value = skill;
      versions.value = data.versions;
    }
  } catch (e) {
    if (rev === revision && !disposed) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
  } finally {
    if (rev === revision && !disposed) loading.value = false;
  }
}
function edit() {
  if (!selected.value?.enabled) return;
  draft.description = selected.value.description;
  draft.when_to_use = selected.value.when_to_use || "";
  draft.instructions = selected.value.body || "";
  draft.note = "";
  editing.value = true;
}
async function write(path: string, method: string, body?: unknown) {
  if (busy.value || loading.value || !selected.value) return;
  busy.value = true;
  failed.value = false;
  notice.value = "";
  const name = selected.value.name;
  try {
    const result = await requestJson<{ changed?: boolean }>(path, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (disposed) return;
    await select(name, true);
    await list();
    if (!failed.value)
      notice.value =
        result.changed === false ? "内容没有变化。" : "操作已完成。";
  } catch (e) {
    if (!disposed) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
  } finally {
    if (!disposed) busy.value = false;
  }
}
async function readVersion(version: string) {
  if (!selected.value || busy.value) return;
  const rev = ++revision;
  loading.value = true;
  try {
    const data = await requestJson<Skill>(
      `${endpoint(selected.value.name)}/versions/${encodeURIComponent(version)}`,
    );
    if (rev === revision && !disposed) {
      historical.value = data;
      restoreTarget.value = "";
    }
  } catch (e) {
    if (rev === revision && !disposed) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
  } finally {
    if (rev === revision && !disposed) loading.value = false;
  }
}
onMounted(list);
onBeforeUnmount(() => {
  disposed = true;
  ++revision;
});
</script>
<template>
  <section class="page-stack">
    <header class="page-heading">
      <p class="eyebrow">慢慢了解你的做事方式</p>
      <h1>习惯与技能</h1>
      <p class="muted">查看学习到的规则，决定哪些继续使用，哪些需要调整。</p>
    </header>
    <p
      v-if="notice"
      :class="['notice', { error: failed }]"
      :role="failed ? 'alert' : 'status'"
    >
      {{ notice }}
    </p>
    <div class="skill-layout">
      <aside class="panel skill-list">
        <div class="row-actions">
          <h2>全部规则</h2>
          <button class="button" :disabled="busy || loading" @click="list">
            刷新
          </button>
        </div>
        <p v-if="listLoading" role="status" class="muted">正在读取规则列表…</p>
        <p v-else-if="!skills.length && !failed" class="empty-state">
          还没有规则。明确的长期反馈可在对话中形成学习候选，由你确认。
        </p>
        <button
          v-for="skill in skills"
          :key="skill.name"
          class="skill-item"
          :disabled="busy || loading"
          :aria-pressed="selected?.name === skill.name"
          @click="select(skill.name)"
        >
          <strong>{{ skill.name }}</strong
          ><span class="muted">{{ skill.description }}</span
          ><span class="badge"
            >{{ skill.enabled ? "已启用" : "已停用" }} ·
            {{ skill.version }}</span
          >
        </button>
      </aside>
      <div class="page-stack skill-detail">
        <p v-if="loading" role="status">正在读取规则…</p>
        <section v-if="selected" class="panel page-stack">
          <div class="row-actions">
            <h2>{{ selected.name }}</h2>
            <span class="badge"
              >{{ selected.enabled ? "已启用" : "已停用" }} ·
              {{ selected.version }}</span
            >
          </div>
          <p class="muted">{{ selected.description }}</p>
          <p v-if="selected.when_to_use">
            <strong>适用时机：</strong>{{ selected.when_to_use }}
          </p>
          <div class="row-actions">
            <button
              class="button"
              :disabled="busy || loading || !selected.enabled"
              @click="edit"
            >
              编辑规则</button
            ><button
              class="button"
              :disabled="busy || loading"
              @click="
                write(
                  `${endpoint(selected.name)}/${selected.enabled ? 'disable' : 'enable'}`,
                  'POST',
                )
              "
            >
              {{ selected.enabled ? "停用" : "启用" }}
            </button>
          </div>
          <form
            v-if="editing"
            class="page-stack"
            @submit.prevent="write(endpoint(selected.name), 'PUT', draft)"
          >
            <label class="field"
              >说明<input
                v-model="draft.description"
                :disabled="busy || loading" /></label
            ><label class="field"
              >适用时机<input
                v-model="draft.when_to_use"
                :disabled="busy || loading" /></label
            ><label class="field"
              >规则正文<textarea
                v-model="draft.instructions"
                rows="10"
                required
                :disabled="busy || loading"
              /></label
            ><label class="field"
              >修改备注<input v-model="draft.note" :disabled="busy || loading"
            /></label>
            <div class="row-actions">
              <button
                class="button primary"
                :disabled="busy || loading"
                type="submit"
              >
                保存规则</button
              ><button
                class="button"
                :disabled="busy || loading"
                type="button"
                @click="editing = false"
              >
                取消
              </button>
            </div>
          </form>
          <pre v-else class="skill-body">{{ selected.body }}</pre>
          <details v-if="selected.notes">
            <summary>演化记录</summary>
            <pre>{{ selected.notes }}</pre>
          </details>
          <div class="version-list">
            <h3>版本记录</h3>
            <div class="row-actions">
              <button
                v-for="version in versions"
                :key="version.version"
                class="button"
                :disabled="busy || loading"
                @click="readVersion(version.version)"
              >
                {{ version.version }}{{ version.current ? "（当前）" : "" }}
              </button>
            </div>
          </div>
        </section>
        <section v-if="historical" class="panel page-stack">
          <h2>版本 {{ historical.version }}</h2>
          <pre class="skill-body">{{ historical.body }}</pre>
          <p class="muted small">
            恢复将还原该版本的完整规则与元信息，并生成新版本。
          </p>
          <button
            class="button"
            :disabled="busy || loading"
            @click="restoreTarget = historical.version"
          >
            恢复此版本
          </button>
          <div v-if="restoreTarget" class="notice">
            <p>确认恢复版本 {{ restoreTarget }}？</p>
            <div class="row-actions">
              <button
                class="button primary"
                :disabled="busy || loading"
                @click="
                  write(
                    `${endpoint(selected!.name)}/versions/${encodeURIComponent(restoreTarget)}/restore`,
                    'POST',
                  )
                "
              >
                确认恢复</button
              ><button
                class="button"
                :disabled="busy || loading"
                @click="restoreTarget = ''"
              >
                取消
              </button>
            </div>
          </div>
        </section>
        <p v-if="!selected && !loading" class="panel empty-state">
          选择一条规则，查看具体内容。
        </p>
      </div>
    </div>
  </section>
</template>
<style scoped>
.skill-layout {
  display: grid;
  grid-template-columns: minmax(200px, 30%) minmax(0, 1fr);
  gap: 22px;
}
.skill-list {
  align-self: start;
  padding: 15px;
}
.skill-list h2 {
  font-size: 1rem;
  margin: 0;
}
.skill-item {
  display: grid;
  gap: 7px;
  text-align: left;
  padding: 14px 10px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  width: 100%;
  overflow-wrap: anywhere;
}
.skill-item[aria-pressed="true"] {
  background: var(--accent);
  border-radius: 8px;
}
.skill-item > .muted {
  font-size: 0.78rem;
}
.skill-item .badge {
  justify-self: start;
}
.skill-detail {
  width: 100%;
  min-width: 0;
}
.skill-detail h2,
.skill-detail p {
  margin-bottom: 0;
}
.skill-body {
  font: inherit;
  font-size: 0.88rem;
  white-space: pre-wrap;
  margin: 0;
}
.version-list {
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
@media (max-width: 900px) {
  .skill-layout {
    grid-template-columns: 1fr;
  }
  .skill-list {
    max-height: 340px;
    overflow: auto;
  }
}
</style>
