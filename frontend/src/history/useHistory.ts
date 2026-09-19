import { ref } from "vue";
import { errorMessage, requestJson } from "../api/http";
import type { SessionDetail } from "../api/types";

export function createHistory() {
  const selectedId = ref("");
  const detail = ref<SessionDetail | null>(null);
  const loading = ref(false);
  const error = ref("");
  let revision = 0;
  let controller: AbortController | null = null;
  function clear() {
    ++revision;
    controller?.abort();
    selectedId.value = "";
    detail.value = null;
    error.value = "";
    loading.value = false;
  }
  async function load(id: string) {
    const ownRevision = ++revision;
    controller?.abort();
    controller = new AbortController();
    selectedId.value = id;
    detail.value = null;
    loading.value = true;
    error.value = "";
    try {
      const result = await requestJson<SessionDetail>(
        `/api/sessions/${encodeURIComponent(id)}`,
        { signal: controller.signal },
      );
      if (ownRevision === revision) detail.value = result;
    } catch (cause) {
      if (ownRevision === revision) error.value = errorMessage(cause);
    } finally {
      if (ownRevision === revision) loading.value = false;
    }
  }
  return { selectedId, detail, loading, error, load, clear };
}

interface ToolResultPage {
  text: string;
  total_chars: number;
  next_offset?: number | null;
  has_more?: boolean;
  query?: string;
  match_offset?: number;
  window_start?: number;
  window_end?: number;
  has_more_before?: boolean;
  has_more_after?: boolean;
}

/** One reader belongs to one session/ref pair and is disposed with its trace row. */
export function createToolResultReader(sessionId: string, artifactRef: string) {
  const open = ref(false);
  const loading = ref(false);
  const error = ref("");
  const text = ref("");
  const query = ref("");
  const appliedQuery = ref("");
  const total = ref(0);
  const offset = ref<number | null>(0);
  const hasMore = ref(false);
  const location = ref("");
  let revision = 0;
  let controller: AbortController | null = null;
  function close() {
    ++revision;
    controller?.abort();
    open.value = false;
    loading.value = false;
  }
  async function load(mode: "first" | "more" | "search" = "first") {
    if (
      mode === "more" &&
      (loading.value || !hasMore.value || appliedQuery.value)
    )
      return;
    const needle = mode === "search" ? query.value.trim() : "";
    const start = mode === "more" ? (offset.value ?? 0) : 0;
    const ownRevision = ++revision;
    controller?.abort();
    controller = new AbortController();
    open.value = true;
    loading.value = true;
    error.value = "";
    if (mode !== "more") {
      text.value = "";
      hasMore.value = false;
      location.value = "";
    }
    const params = new URLSearchParams({
      offset: String(start),
      limit: "8000",
    });
    if (needle) params.set("query", needle);
    try {
      const page = await requestJson<ToolResultPage>(
        `/api/sessions/${encodeURIComponent(sessionId)}/tool-results/${encodeURIComponent(artifactRef)}?${params}`,
        { signal: controller.signal },
      );
      if (ownRevision !== revision) return;
      text.value = mode === "more" ? text.value + page.text : page.text;
      total.value = page.total_chars;
      offset.value = page.next_offset ?? null;
      hasMore.value = Boolean(page.has_more && page.next_offset != null);
      appliedQuery.value = needle;
      location.value = needle
        ? `命中位置 ${page.match_offset ?? 0}，显示原文 ${page.window_start ?? 0}–${page.window_end ?? 0} / ${page.total_chars} 字`
        : `已读取 ${Array.from(text.value).length} / ${page.total_chars} 字${hasMore.value ? "" : "（已到结尾）"}`;
    } catch (cause) {
      if (ownRevision === revision) error.value = errorMessage(cause);
    } finally {
      if (ownRevision === revision) loading.value = false;
    }
  }
  async function toggle() {
    if (open.value) close();
    else {
      query.value = "";
      appliedQuery.value = "";
      await load();
    }
  }
  async function reset() {
    query.value = "";
    appliedQuery.value = "";
    await load();
  }
  return {
    open,
    loading,
    error,
    text,
    query,
    appliedQuery,
    total,
    hasMore,
    location,
    load,
    toggle,
    close,
    reset,
  };
}
