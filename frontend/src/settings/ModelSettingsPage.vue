<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { errorMessage, requestJson } from "../api/http";
import type { ModelConfig } from "../api/types";
const cfg = ref<ModelConfig | null>(null);
const draft = reactive({
  model: "",
  api_base: "",
  api_key: "",
  thinking: false,
  max_turns: "",
});
const busy = ref(false);
const loading = ref(true);
const notice = ref("");
const failed = ref(false);
let disposed = false;
function adopt(value: ModelConfig) {
  cfg.value = value;
  draft.model = value.model;
  draft.api_base = value.api_base;
  draft.thinking = value.thinking;
  draft.max_turns = value.max_turns == null ? "" : String(value.max_turns);
  draft.api_key = "";
}
async function load() {
  loading.value = true;
  try {
    const data = await requestJson<ModelConfig>("/api/config");
    if (!disposed) adopt(data);
  } catch (e) {
    if (!disposed) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
  } finally {
    if (!disposed) loading.value = false;
  }
}
async function save() {
  if (busy.value) return;
  busy.value = true;
  failed.value = false;
  notice.value = "";
  try {
    const value = await requestJson<ModelConfig>("/api/config", {
      method: "PUT",
      body: JSON.stringify({
        ...draft,
        max_turns: draft.max_turns ? Number(draft.max_turns) : null,
      }),
    });
    if (!disposed) {
      adopt(value);
      notice.value = "配置已保存，下一轮对话使用服务端的有效配置。";
    }
  } catch (e) {
    if (!disposed) {
      notice.value = errorMessage(e);
      failed.value = true;
    }
  } finally {
    draft.api_key = "";
    if (!disposed) busy.value = false;
  }
}
onMounted(load);
onBeforeUnmount(() => {
  disposed = true;
  draft.api_key = "";
});
</script>
<template>
  <section class="page-stack">
    <header class="page-heading">
      <p class="eyebrow">连接你的助理</p>
      <h1>模型配置</h1>
      <p class="muted">设置使用的模型与接口，已有对话会继续保留。</p>
    </header>
    <p
      v-if="notice"
      :class="['notice', { error: failed }]"
      :role="failed ? 'alert' : 'status'"
    >
      {{ notice }}
    </p>
    <p v-if="loading" role="status">正在读取配置…</p>
    <button v-else-if="!cfg" class="button" @click="load">重新读取</button>
    <form v-else class="panel page-stack" @submit.prevent="save">
      <p class="muted">
        {{ cfg.configured ? "已配置模型凭据" : "尚未配置模型凭据" }}
        {{ cfg.api_key_hint }}
      </p>
      <label class="field"
        >模型名称<input
          v-model="draft.model"
          required
          placeholder="deepseek-v4-pro"
          :disabled="busy" /></label
      ><label class="field"
        >API 地址<input
          v-model="draft.api_base"
          type="url"
          required
          :disabled="busy" /></label
      ><label class="field"
        >API Key（留空保留现有值）<input
          v-model="draft.api_key"
          type="password"
          autocomplete="new-password"
          :disabled="busy"
          placeholder="填写新的密钥"
      /></label>
      <div class="form-grid">
        <label
          ><input v-model="draft.thinking" type="checkbox" :disabled="busy" />
          启用思考模式</label
        ><label class="field"
          >最大工具轮次<input
            v-model="draft.max_turns"
            type="number"
            min="1"
            step="1"
            :disabled="busy"
            placeholder="使用运行时默认值"
        /></label>
      </div>
      <p class="muted small">
        部署环境变量优先于页面配置。保存后显示服务端实际生效的值；密钥不会保存在浏览器。
      </p>
      <button class="button primary" :disabled="busy" type="submit">
        {{ busy ? "保存中…" : "保存配置" }}
      </button>
    </form>
  </section>
</template>
