<script setup lang="ts">
import { onBeforeUnmount } from "vue";
import { createToolResultReader } from "./useHistory";
const props = defineProps<{ sessionId: string; artifactRef: string }>();
const {
  open,
  loading,
  error,
  text,
  query,
  appliedQuery,
  hasMore,
  location,
  load,
  toggle,
  close,
  reset,
} = createToolResultReader(props.sessionId, props.artifactRef);
onBeforeUnmount(close);
</script>

<template>
  <div class="tool-result">
    <button class="button" type="button" :aria-expanded="open" @click="toggle">
      {{ open ? "收起原文" : "查看完整原文" }}
    </button>
    <div v-if="open" class="original-box">
      <form class="result-search" @submit.prevent="load('search')">
        <label class="field"
          >在原文中查找<input
            v-model="query"
            type="search"
            placeholder="输入关键词"
        /></label>
        <button class="button" :disabled="!query.trim()" type="submit">
          查找
        </button>
        <button class="button" type="button" @click="reset">从头查看</button>
      </form>
      <p v-if="loading" role="status" class="muted">正在读取原文…</p>
      <p v-if="error" role="alert" class="notice error">
        原文读取失败：{{ error }}
      </p>
      <pre v-if="text" class="original-text">{{ text }}</pre>
      <p v-if="!loading && !error && !text" class="muted">原文为空。</p>
      <p v-if="location" class="muted">{{ location }}</p>
      <p v-if="appliedQuery" class="muted">
        当前显示命中片段；点击“从头查看”可分页阅读全文。
      </p>
      <button
        v-if="hasMore"
        class="button"
        :disabled="loading"
        @click="load('more')"
      >
        继续加载
      </button>
    </div>
  </div>
</template>

<style scoped>
.tool-result {
  margin-top: 0.8rem;
}
.original-box {
  margin-top: 0.8rem;
  padding: 1rem;
  background: var(--bg);
  border-radius: 12px;
}
.result-search {
  display: flex;
  gap: 0.5rem;
  align-items: end;
  flex-wrap: wrap;
}
.result-search .field {
  flex: 1;
  min-width: 140px;
}
.original-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: inherit;
  line-height: 1.7;
  max-height: 500px;
  overflow-y: auto;
}
</style>
