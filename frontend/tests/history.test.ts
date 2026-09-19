import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import {
  createHistory,
  createToolResultReader,
} from "../src/history/useHistory";
import HistoryPage from "../src/history/HistoryPage.vue";
import ToolResult from "../src/history/ToolResult.vue";
import { useConversation } from "../src/conversation/useConversation";

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
afterEach(() => {
  useConversation().newSession();
  vi.unstubAllGlobals();
});

describe("history state and artifact reading", () => {
  it("loads sequential pages using server offsets and handles search windows separately from pagination", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({
          text: "甲🌿",
          offset: 0,
          next_offset: 2,
          has_more: true,
          total_chars: 5,
        }),
      )
      .mockResolvedValueOnce(
        json({
          text: "乙丙丁",
          offset: 2,
          next_offset: null,
          has_more: false,
          total_chars: 5,
        }),
      )
      .mockResolvedValueOnce(
        json({
          text: "乙丙丁",
          query: "丙",
          match_offset: 3,
          window_start: 2,
          window_end: 5,
          total_chars: 5,
          has_more_before: true,
          has_more_after: false,
        }),
      )
      .mockResolvedValueOnce(
        json({
          text: "甲🌿",
          offset: 0,
          next_offset: 2,
          has_more: true,
          total_chars: 5,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const reader = createToolResultReader("one", "result-one");
    await reader.toggle();
    expect(reader.text.value).toBe("甲🌿");
    expect(reader.hasMore.value).toBe(true);
    await reader.load("more");
    expect(reader.text.value).toBe("甲🌿乙丙丁");
    expect(reader.hasMore.value).toBe(false);
    expect(fetchMock.mock.calls[1]?.[0]).toContain("offset=2");
    reader.query.value = "丙";
    await reader.load("search");
    expect(reader.text.value).toBe("乙丙丁");
    expect(reader.location.value).toContain("命中位置 3");
    expect(reader.hasMore.value).toBe(false);
    expect(fetchMock.mock.calls[2]?.[0]).toContain("query=%E4%B8%99");
    await reader.reset();
    expect(reader.query.value).toBe("");
    expect(reader.appliedQuery.value).toBe("");
    expect(reader.text.value).toBe("甲🌿");
    expect(fetchMock.mock.calls[3]?.[0]).not.toContain("query=");
  });

  it("invalidates in-flight reads on collapse, reopens from the start and isolates equal refs in different sessions", async () => {
    const stale = deferred<Response>();
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce(
        json({
          text: "重新读取",
          next_offset: null,
          has_more: false,
          total_chars: 4,
        }),
      )
      .mockResolvedValueOnce(
        json({
          text: "另一个会话",
          next_offset: null,
          has_more: false,
          total_chars: 5,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const first = createToolResultReader("one", "shared-name");
    const pending = first.toggle();
    first.close();
    await first.toggle();
    stale.resolve(
      json({
        text: "过期内容",
        next_offset: 4,
        has_more: true,
        total_chars: 10,
      }),
    );
    await pending;
    expect(first.text.value).toBe("重新读取");
    expect(first.hasMore.value).toBe(false);
    const second = createToolResultReader("two", "shared-name");
    await second.toggle();
    expect(second.text.value).toBe("另一个会话");
    expect(first.text.value).toBe("重新读取");
    expect(fetchMock.mock.calls[2]?.[0]).toContain(
      "/sessions/two/tool-results/shared-name",
    );
  });

  it("lets a new search replace a pending page and keeps deleted-artifact errors visible", async () => {
    const stale = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockReturnValueOnce(stale.promise)
        .mockResolvedValueOnce(
          json({
            text: "搜索片段",
            query: "搜索",
            match_offset: 42,
            window_start: 40,
            window_end: 44,
            total_chars: 100,
          }),
        )
        .mockResolvedValueOnce(
          json({ ok: false, detail: "会话已删除，原文不存在" }, 404),
        ),
    );
    const reader = createToolResultReader("one", "a");
    const initial = reader.toggle();
    reader.query.value = "搜索";
    await reader.load("search");
    stale.resolve(
      json({
        text: "旧页",
        next_offset: null,
        has_more: false,
        total_chars: 2,
      }),
    );
    await initial;
    expect(reader.text.value).toBe("搜索片段");
    expect(reader.location.value).toContain("42");
    await reader.reset();
    expect(reader.error.value).toContain("会话已删除");
    expect(reader.text.value).toBe("");
  });

  it("does not let old session detail or a cleared request recreate a history selection", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise),
    );
    const history = createHistory();
    const one = history.load("one");
    const two = history.load("two");
    second.resolve(
      json({
        session_id: "two",
        messages: [],
        trace: [],
        trace_display: [],
        active: false,
      }),
    );
    await two;
    first.resolve(
      json({
        session_id: "one",
        messages: [],
        trace: [],
        trace_display: [],
        active: false,
      }),
    );
    await one;
    expect(history.detail.value?.session_id).toBe("two");
    history.clear();
    expect(history.detail.value).toBeNull();
    expect(history.selectedId.value).toBe("");
  });
});

describe("history UI", () => {
  it("requires deletion confirmation, removes the selected history and refreshes the session list", async () => {
    let deleted = false;
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        deleted = true;
        return Promise.resolve(json({ ok: true, session_id: "one" }));
      }
      return Promise.resolve(
        path === "/api/sessions"
          ? json({
              sessions: deleted
                ? []
                : [{ session_id: "one", title: "可删除的会话", messages: 1 }],
            })
          : json({
              session_id: "one",
              messages: [{ role: "user", content: "旧内容" }],
              trace: [],
              trace_display: [],
              active: false,
            }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/", component: HistoryPage }],
    });
    await router.push("/");
    const wrapper = mount(HistoryPage, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get(".session-item").trigger("click");
    await flushPromises();
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "删除会话")!
      .trigger("click");
    expect(deleted).toBe(false);
    expect(wrapper.text()).toContain("执行记录和工具原文都将被清除");
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "确认删除")!
      .trigger("click");
    await flushPromises();
    expect(deleted).toBe(true);
    expect(wrapper.find(".session-item").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("旧内容");
    expect(wrapper.text()).toContain("会话及其执行记录已删除");
    wrapper.unmount();
  });

  it("keeps message history and raw trace accessible, follows structured refs only and continues on the canonical route", async () => {
    const detail = {
      session_id: "one",
      messages: [{ role: "assistant", content: "完整展示历史" }],
      active: false,
      trace: [
        { type: "message", text: "原始片段", turn: 1 },
        { type: "assistant", text: "完整原始回复", turn: 1 },
        {
          type: "tool_result",
          name: "search",
          result: "请读取 ref fake-name",
          truncated: true,
        },
        {
          type: "tool_result",
          name: "search",
          result: "预览",
          ref: "real-ref",
          truncated: true,
        },
      ],
      trace_display: [],
    };
    const fetchMock = vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/sessions"
          ? json({
              sessions: [
                { session_id: "one", title: "今天的对话", messages: 1 },
              ],
            })
          : path.includes("/tool-results/")
            ? json({
                text: "真实原文",
                next_offset: null,
                has_more: false,
                total_chars: 4,
              })
            : json(detail),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/history", component: HistoryPage },
        { path: "/conversation", component: { template: "<div>chat</div>" } },
      ],
    });
    await router.push("/history");
    await router.isReady();
    const wrapper = mount(HistoryPage, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get(".session-item").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("完整展示历史");
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "原始执行过程")!
      .trigger("click");
    expect(wrapper.text()).toContain("原始片段");
    expect(wrapper.text()).toContain("完整原始回复");
    expect(wrapper.findAllComponents(ToolResult)).toHaveLength(1);
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "查看完整原文")!
      .trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("真实原文");
    expect(
      fetchMock.mock.calls
        .filter(([path]) => path.includes("/tool-results/"))
        .map(([path]) => path),
    ).toEqual(["/api/sessions/one/tool-results/real-ref?offset=0&limit=8000"]);
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "继续这段对话")!
      .trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/conversation");
    expect(useConversation().sessionId.value).toBe("one");
    wrapper.unmount();
  });

  it("shows a failed ref read, then refetches instead of showing cached text when reopened", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          json({
            text: "首次原文",
            total_chars: 4,
            next_offset: null,
            has_more: false,
          }),
        )
        .mockResolvedValueOnce(json({ ok: false, detail: "会话已删除" }, 404)),
    );
    const wrapper = mount(ToolResult, {
      props: { sessionId: "one", artifactRef: "a" },
    });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("首次原文");
    await wrapper.get("button").trigger("click");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("会话已删除");
    expect(wrapper.text()).not.toContain("首次原文");
    wrapper.unmount();
  });
});
