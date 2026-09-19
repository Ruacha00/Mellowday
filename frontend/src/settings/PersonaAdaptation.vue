<script setup lang="ts">
import { onMounted, ref } from "vue";
import { errorMessage, requestJson } from "../api/http";
interface Rule {
  id: string;
  scene: string;
  behavior: string;
  example: string;
  enabled: boolean;
  locked: boolean;
  source: { quote: string; created_at: string }[];
  created_at: string;
}
interface Adaptation {
  paused: boolean;
  version: number;
  rules: Rule[];
  history: { version: number; action: string; created_at: string }[];
}
const actions: Record<string, string> = {
  add: "新增习惯",
  update: "调整习惯",
  undo: "撤销习惯",
  lock: "锁定习惯",
  unlock: "解除锁定",
  pause: "暂停演化",
  resume: "恢复演化",
  reset: "重置习惯",
  core_changed: "核心设定更新",
};
const data = ref<Adaptation>(),
  error = ref(""),
  busy = ref(false),
  resetting = ref(false);
async function load() {
  try {
    data.value = await requestJson<Adaptation>("/api/persona/adaptation");
    error.value = "";
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function change(path: string, body?: unknown, method = "POST") {
  busy.value = true;
  try {
    await requestJson("/api/persona/adaptation" + path, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    resetting.value = false;
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <section class="panel page-stack">
    <div class="calendar-actions">
      <div>
        <h2>逐渐形成的习惯</h2>
        <p class="muted small">从你的反馈中适应表达，核心设定始终由你决定。</p>
      </div>
      <button
        v-if="data"
        class="button"
        :disabled="busy"
        @click="change('', { paused: !data.paused }, 'PUT')"
      >
        {{ data.paused ? "恢复演化" : "暂停演化" }}
      </button>
    </div>
    <p v-if="error" class="notice error" role="alert">
      {{ error }} <button class="button" @click="load">重试</button>
    </p>
    <template v-if="data"
      ><p class="muted small">
        版本 {{ data.version }} ·
        {{ data.paused ? "已暂停自动更新" : "自动适应已开启" }}
      </p>
      <p v-if="!data.rules.length" class="muted">
        还没有形成新的习惯。没有足够反馈时，会保持原样。
      </p>
      <article v-for="rule in data.rules" :key="rule.id" class="persona-rule">
        <div class="calendar-actions">
          <h3>{{ rule.scene }}</h3>
          <span class="muted small"
            >{{ rule.enabled ? "生效中" : "已停用"
            }}{{ rule.locked ? " · 已锁定" : "" }}</span
          >
        </div>
        <p>{{ rule.behavior }}</p>
        <blockquote v-if="rule.example">{{ rule.example }}</blockquote>
        <details>
          <summary>学习依据</summary>
          <blockquote v-for="(source, index) in rule.source" :key="index">
            {{ source.quote }}
            <footer class="muted small">
              {{ new Date(source.created_at).toLocaleString() }}
            </footer>
          </blockquote>
        </details>
        <div class="calendar-actions">
          <button
            class="button"
            :disabled="busy"
            @click="
              change('/' + encodeURIComponent(rule.id) + '/lock', {
                locked: !rule.locked,
              })
            "
          >
            {{ rule.locked ? "解除锁定" : "锁定习惯" }}</button
          ><button
            class="button"
            :disabled="busy || !rule.enabled"
            @click="change('/' + encodeURIComponent(rule.id) + '/undo')"
          >
            撤销习惯
          </button>
        </div>
      </article>
      <details>
        <summary>变化历史（{{ data.history.length }}）</summary>
        <p
          v-for="(entry, index) in data.history"
          :key="index"
          class="muted small"
        >
          版本 {{ entry.version }} ·
          {{ actions[entry.action] || "习惯已更新" }} ·
          {{ new Date(entry.created_at).toLocaleString() }}
        </p>
      </details>
      <button class="button" :disabled="busy" @click="resetting = true">
        重置可变人格
      </button>
      <div v-if="resetting" class="notice">
        <p>清除逐渐形成的习惯？核心设定不会改变。</p>
        <button class="button" :disabled="busy" @click="change('/reset')">
          确认重置</button
        ><button class="button" @click="resetting = false">取消</button>
      </div></template
    >
  </section>
</template>
