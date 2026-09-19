<script setup lang="ts">
import { onMounted, ref } from "vue";
import { errorMessage, requestJson } from "../api/http";
const data = ref<{
  ok: boolean;
  app: string;
  version: string;
  model_configured: boolean;
} | null>(null);
const busy = ref(false);
const error = ref("");
async function load() {
  busy.value = true;
  error.value = "";
  try {
    data.value = await requestJson("/api/health");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <section class="page-stack">
    <header class="page-heading">
      <p class="eyebrow">这里的运行情况</p>
      <h1>运行状态</h1>
      <p class="muted">检查服务连接与模型配置。</p>
    </header>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <div v-if="data" class="panel">
      <h2>{{ data.ok ? "服务连接正常" : "服务暂不可用" }}</h2>
      <dl>
        <dt>应用</dt>
        <dd>{{ data.app }}</dd>
        <dt>版本</dt>
        <dd>{{ data.version }}</dd>
        <dt>模型凭据</dt>
        <dd>{{ data.model_configured ? "已配置" : "未配置" }}</dd>
      </dl>
      <p class="muted small">
        健康检查不会请求模型。一次真实对话才能验证模型连接、权限和余额。
      </p>
    </div>
    <button class="button" :disabled="busy" @click="load">
      {{ busy ? "检查中…" : "重新检查" }}
    </button>
  </section>
</template>
