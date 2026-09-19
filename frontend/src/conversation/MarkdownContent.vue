<script setup lang="ts">
import { computed } from "vue";
import MarkdownIt from "markdown-it";
const props = defineProps<{ content: string }>();
const markdown = new MarkdownIt({ html: false, linkify: false, breaks: true });
const html = computed(() => markdown.render(props.content));
</script>

<template><div class="markdown-content" v-html="html" /></template>

<style scoped>
.markdown-content {
  overflow-wrap: anywhere;
  line-height: 1.75;
}
.markdown-content :deep(p:first-child) {
  margin-top: 0;
}
.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-content :deep(pre) {
  overflow-x: auto;
  white-space: pre;
  padding: 1rem;
  border-radius: 12px;
  background: var(--bg);
}
.markdown-content :deep(a) {
  color: var(--accent-strong);
}
.markdown-content :deep(table) {
  display: block;
  overflow-x: auto;
  border-collapse: collapse;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid var(--border);
  padding: 0.5rem;
}
.markdown-content :deep(img) {
  max-width: 100%;
}
</style>
