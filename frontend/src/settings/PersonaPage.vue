<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { errorMessage, requestJson } from "../api/http";

import PersonaAdaptation from "./PersonaAdaptation.vue";
const fields = [
  ["name", "称呼", 80],
  ["identity", "身份", 1200],
  ["character", "性格", 1200],
  ["speaking_style", "说话方式", 1200],
  ["relationship", "关系定位", 1200],
  ["boundaries", "交流边界", 1200],
  ["examples", "说话示例", 1200],
] as const;
type Persona = Record<(typeof fields)[number][0], string>;
const draft = reactive<Persona>({
  name: "",
  identity: "",
  character: "",
  speaking_style: "",
  relationship: "",
  boundaries: "",
  examples: "",
});
const loaded = ref(false);
const busy = ref(false);
const notice = ref("");
const failed = ref(false);
const controller = new AbortController();
let disposed = false;
async function load() {
  if (busy.value) return;
  busy.value = true;
  notice.value = "";
  failed.value = false;
  try {
    const value = await requestJson<Persona>("/api/persona", {
      signal: controller.signal,
    });
    if (!disposed) {
      Object.assign(draft, value);
      loaded.value = true;
    }
  } catch (error) {
    if (!disposed) {
      notice.value = errorMessage(error);
      failed.value = true;
    }
  } finally {
    if (!disposed) busy.value = false;
  }
}
async function save() {
  if (busy.value || !loaded.value) return;
  busy.value = true;
  failed.value = false;
  notice.value = "";
  try {
    const value = await requestJson<Persona>("/api/persona", {
      method: "PUT",
      body: JSON.stringify(draft),
      signal: controller.signal,
    });
    if (!disposed) {
      Object.assign(draft, value);
      notice.value = "人格已保存，从下一轮回复开始生效。已有聊天记录保持原样。";
    }
  } catch (error) {
    if (!disposed) {
      notice.value = errorMessage(error);
      failed.value = true;
    }
  } finally {
    if (!disposed) busy.value = false;
  }
}
onMounted(load);
onBeforeUnmount(() => {
  disposed = true;
  controller.abort();
});
</script>

<template>
  <section class="page-stack">
    <header class="page-heading">
      <p class="eyebrow">慢慢熟悉彼此</p>
      <h1>人格</h1>
      <p class="muted">
        设定你希望如何相处，让聊天、倾听和日常帮忙都有熟悉的感觉。
      </p>
    </header>
    <p
      v-if="notice"
      :class="['notice', { error: failed }]"
      :role="failed ? 'alert' : 'status'"
    >
      {{ notice }}
    </p>
    <p v-if="!loaded && busy" role="status">正在读取人格…</p>
    <button v-else-if="!loaded" class="button" @click="load">重新读取</button>
    <form v-else class="panel page-stack" @submit.prevent="save">
      <p class="muted">
        这些设定用于聊天表达，由你管理。对你的记忆和学到的做事习惯会分别保存，不会自动改写这里。
      </p>
      <label v-for="[key, label, limit] in fields" :key="key" class="field">
        {{ label }}
        <input
          v-if="key === 'name'"
          v-model="draft[key]"
          :maxlength="limit"
          :disabled="busy"
        />
        <textarea
          v-else
          v-model="draft[key]"
          rows="3"
          :maxlength="limit"
          :disabled="busy"
        />
      </label>
      <p class="muted small">
        留空会采用默认设定。聊天风格不会改变操作确认、真实记录或权限。
      </p>
      <button class="button primary" type="submit" :disabled="busy">
        {{ busy ? "保存中…" : "保存人格" }}
      </button>
    </form>
    <PersonaAdaptation />
  </section>
</template>
