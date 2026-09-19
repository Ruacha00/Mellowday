<script setup lang="ts">
import type { RuntimeEvent } from "../api/types";
defineProps<{ events: RuntimeEvent[] }>();
const labels: Record<string, string> = {
  skill_candidate_proposed: "发现可学习的规则",
  skill_candidate_applied: "规则已应用",
  skill_write_denied: "规则写入被拒绝",
  skill_candidate_failed: "规则处理失败",
  skill_candidate_skipped: "已跳过规则学习",
  tool_start: "正在调用工具",
  tool_result: "工具返回结果",
  warning: "提醒",
  notice: "提示",
  error: "处理失败",
  retry: "正在重试",
  token_usage: "本轮用量",
  busy_start: "正在处理",
  busy_end: "处理完成",
  subagent_start: "协作任务开始",
  subagent_end: "协作任务结束",
  skill_list: "可用规则",
  memory_list: "相关记忆",
  plan: "处理计划",
};
function details(event: RuntimeEvent) {
  if (event.type === "token_usage")
    return `输入 ${event.input ?? 0} · 输出 ${event.output ?? 0}`;
  const value =
    event.message ??
    event.summary ??
    event.result ??
    event.arguments ??
    event.reason ??
    event.text;
  const text =
    typeof value === "string"
      ? value
      : value == null
        ? ""
        : JSON.stringify(value, null, 2);
  return text.length > 2400
    ? `${text.slice(0, 2400)}\n…完整记录可在会话历史中查看。`
    : text;
}
</script>

<template>
  <div v-if="events.length" class="event-feed" aria-label="本轮执行与学习反馈">
    <details
      v-for="(event, index) in events"
      :key="index"
      :open="
        event.type.startsWith('skill_') ||
        event.type === 'error' ||
        event.type === 'warning'
      "
      :class="[
        'event-item',
        {
          'event-error':
            event.type === 'error' || event.type === 'skill_candidate_failed',
        },
      ]"
    >
      <summary>
        {{ labels[event.type] || "运行提示" }}
        <span class="muted">{{ event.skill || event.name || "" }}</span>
      </summary>
      <pre v-if="details(event)">{{ details(event) }}</pre>
      <p v-if="event.ref" class="muted">完整原文已保存，可在会话历史中查看。</p>
    </details>
  </div>
</template>

<style scoped>
.event-feed {
  display: grid;
  gap: 0.6rem;
}
.event-item {
  padding: 0.8rem 1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  font-size: 0.9rem;
}
.event-error {
  border-color: #bb5b59;
}
summary {
  cursor: pointer;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
  margin-bottom: 0;
}
</style>
