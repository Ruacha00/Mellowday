import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import {
  createConversation,
  useConversation,
} from "../src/conversation/useConversation";
import ConversationPage from "../src/conversation/ConversationPage.vue";
import EventFeed from "../src/conversation/EventFeed.vue";
import MarkdownContent from "../src/conversation/MarkdownContent.vue";
import type { RuntimeEvent } from "../src/api/types";

const json = (data: unknown) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
function chatStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const cancelled = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value;
    },
    cancel: cancelled,
  });
  return {
    response: new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    }),
    emit(event: RuntimeEvent) {
      controller.enqueue(
        new TextEncoder().encode(`data:${JSON.stringify(event)}\n\n`),
      );
    },
    close() {
      controller.close();
    },
    cancelled,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
afterEach(async () => {
  const singleton = useConversation();
  if (singleton.busy.value) {
    await singleton.stop();
    await flushPromises();
  }
  singleton.newSession();
  vi.unstubAllGlobals();
});

describe("conversation lifetime", () => {
  it("keeps the turn active through late learning, deduplicates session-bound confirmations and submits only once", async () => {
    const stream = chatStream();
    const receipt = deferred<Response>();
    const fetchMock = vi.fn((path: string) =>
      path === "/api/chat"
        ? Promise.resolve(stream.response)
        : path.startsWith("/api/confirmations/")
          ? receipt.promise
          : Promise.resolve(json({ sessions: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const conversation = createConversation();
    const pending = conversation.send("帮我记住这个偏好");
    stream.emit({ type: "session", session_id: "one" });
    stream.emit({ type: "text_delta", text: "记好了。" });
    stream.emit({ type: "turn_end" });
    stream.emit({
      type: "skill_candidate_proposed",
      skill: "偏好",
      action: "add",
    });
    stream.emit({
      type: "confirmation",
      id: "token-one",
      session_id: "one",
      summary: "保存偏好？",
    });
    stream.emit({
      type: "confirmation",
      id: "token-one",
      session_id: "one",
      summary: "保存偏好？",
    });
    await flushPromises();
    expect(conversation.busy.value).toBe(true);
    expect(conversation.messages.value[1]?.content).toBe("记好了。");
    expect(conversation.confirmations.value).toHaveLength(1);
    expect(await conversation.selectSession("two")).toBe(false);
    expect(conversation.newSession()).toBe(false);
    expect(await conversation.deleteSession("one")).toBe(false);
    expect(await conversation.send("第二条")).toBe(false);
    const item = conversation.pendingConfirmation.value!;
    const answer = conversation.answerConfirmation(item, true);
    await conversation.answerConfirmation(item, true);
    expect(
      fetchMock.mock.calls.filter(([path]) =>
        path.startsWith("/api/confirmations/"),
      ),
    ).toHaveLength(1);
    receipt.resolve(json({ ok: true, accepted: false, approved: true }));
    await answer;
    expect(item.status).toBe("expired");
    expect(item.result).toContain("没有再次执行");
    stream.emit({
      type: "skill_write_denied",
      skill: "偏好",
      reason: "user_denied",
    });
    stream.emit({ type: "done", session_id: "one" });
    await expect(pending).resolves.toBe(true);
    expect(conversation.busy.value).toBe(false);
    expect(conversation.events.value.map((event) => event.type)).toEqual([
      "skill_candidate_proposed",
      "skill_write_denied",
    ]);
    expect(stream.cancelled).toHaveBeenCalledOnce();
  });

  it("does not create actionable controls without a valid Web token or after the turn ends", async () => {
    const stream = chatStream();
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path === "/api/chat" ? stream.response : json({ sessions: [] }),
        ),
      ),
    );
    const conversation = createConversation();
    const pending = conversation.send("你好");
    stream.emit({ type: "session", session_id: "one" });
    stream.emit({ type: "confirmation", summary: "没有可用确认人" });
    stream.emit({
      type: "confirmation",
      id: "valid",
      session_id: "one",
      summary: "等待确认",
    });
    stream.emit({ type: "done" });
    await pending;
    expect(conversation.confirmations.value).toHaveLength(1);
    expect(conversation.confirmations.value[0]?.status).toBe("expired");
    expect(conversation.pendingConfirmation.value).toBeNull();
    expect(conversation.events.value[0]).toEqual({
      type: "warning",
      message: "没有可用确认人",
    });
  });

  it("rejects cross-session events, preserves partial text, and can send again after an incomplete stream", async () => {
    const first = chatStream();
    const second = chatStream();
    const third = chatStream();
    const streams = [first, second, third];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path === "/api/chat"
            ? streams.shift()!.response
            : json({ sessions: [] }),
        ),
      ),
    );
    const conversation = createConversation();
    const round1 = conversation.send("一");
    first.emit({ type: "session", session_id: "one" });
    first.emit({ type: "text_delta", text: "已收到的文本" });
    first.close();
    expect(await round1).toBe(false);
    expect(conversation.error.value).toContain("连接提前结束");
    expect(conversation.messages.value[1]?.content).toBe("已收到的文本");
    const round2 = conversation.send("二");
    second.emit({ type: "session", session_id: "other" });
    expect(await round2).toBe(false);
    expect(conversation.sessionId.value).toBe("one");
    expect(conversation.error.value).toContain("其他会话");
    const round3 = conversation.send("三");
    third.emit({ type: "session", session_id: "one" });
    third.emit({ type: "text_delta", text: "完成" });
    third.emit({ type: "done" });
    expect(await round3).toBe(true);
    expect(conversation.messages.value.at(-1)?.content).toBe("完成");
  });

  it("ignores late session responses and never lets an earlier load replace a newer selection", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        path.endsWith("/one") ? first.promise : second.promise,
      ),
    );
    const conversation = createConversation();
    const a = conversation.selectSession("one");
    const b = conversation.selectSession("two");
    second.resolve(
      json({
        session_id: "two",
        messages: [{ role: "user", content: "新会话" }],
        trace: [],
        trace_display: [],
        active: false,
      }),
    );
    await b;
    first.resolve(
      json({
        session_id: "one",
        messages: [{ role: "user", content: "旧会话" }],
        trace: [],
        trace_display: [],
        active: false,
      }),
    );
    expect(await a).toBe(false);
    expect(conversation.sessionId.value).toBe("two");
    expect(conversation.messages.value[0]?.content).toBe("新会话");
  });

  it("cancels only the current request without a delayed session-wide abort that could stop the next turn", async () => {
    const stream = chatStream();
    const fetchMock = vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/chat" ? stream.response : json({ sessions: [] }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const conversation = createConversation();
    const pending = conversation.send("一");
    stream.emit({ type: "session", session_id: "one" });
    await flushPromises();
    const stopped = conversation.stop();
    expect(conversation.busy.value).toBe(true);
    expect(await conversation.send("二")).toBe(false);
    await stopped;
    await pending;
    expect(stream.cancelled).toHaveBeenCalledOnce();
    expect(conversation.busy.value).toBe(false);
    expect(fetchMock.mock.calls.some(([path]) => path.endsWith("/abort"))).toBe(
      false,
    );
  });
});

describe("conversation UI", () => {
  it("guards IME and whitespace submission and keeps a failed message draft", async () => {
    const fetchMock = vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/chat"
          ? new Response(
              'data:{"type":"error","message":"请先配置模型"}\n\ndata:{"type":"done"}\n\n',
              { headers: { "Content-Type": "text/event-stream" } },
            )
          : json({ sessions: [] }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(ConversationPage);
    const input = wrapper.get("textarea");
    await input.setValue("   ");
    await wrapper.get("form").trigger("submit");
    await input.setValue("保留这条草稿");
    await input.trigger("compositionstart");
    await input.trigger("keydown", { key: "Enter", isComposing: true });
    expect(fetchMock).not.toHaveBeenCalled();
    await input.trigger("compositionend");
    await input.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(
      fetchMock.mock.calls.filter(([path]) => path === "/api/chat"),
    ).toHaveLength(1);
    expect((input.element as HTMLTextAreaElement).value).toBe("保留这条草稿");
    expect(wrapper.get('[role="alert"]').text()).toContain("请先配置模型");
    wrapper.unmount();
  });

  it("survives page unmount, then renders late learning and confirmation on return", async () => {
    const stream = chatStream();
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path === "/api/chat" ? stream.response : json({ sessions: [] }),
        ),
      ),
    );
    const wrapper = mount(ConversationPage);
    await wrapper.get("textarea").setValue("你好");
    await wrapper.get("form").trigger("submit");
    stream.emit({ type: "session", session_id: "one" });
    stream.emit({ type: "text_delta", text: "回复" });
    stream.emit({ type: "turn_end" });
    await flushPromises();
    wrapper.unmount();
    expect(useConversation().busy.value).toBe(true);
    expect(stream.cancelled).not.toHaveBeenCalled();
    stream.emit({ type: "skill_candidate_proposed", skill: "习惯" });
    stream.emit({
      type: "confirmation",
      id: "late",
      session_id: "one",
      summary: "保存习惯吗？",
    });
    await flushPromises();
    const returned = mount(ConversationPage);
    expect(returned.text()).toContain("发现可学习的规则");
    expect(returned.text()).toContain("保存习惯吗？");
    stream.emit({ type: "done" });
    await flushPromises();
    returned.unmount();
  });

  it("makes every learning terminal state visible and renders Markdown without active HTML or script links", () => {
    const events = [
      "skill_candidate_proposed",
      "skill_candidate_applied",
      "skill_write_denied",
      "skill_candidate_failed",
      "skill_candidate_skipped",
    ].map((type) => ({ type, skill: "习惯" }));
    const feed = mount(EventFeed, { props: { events } });
    for (const label of [
      "发现可学习的规则",
      "规则已应用",
      "规则写入被拒绝",
      "规则处理失败",
      "已跳过规则学习",
    ])
      expect(feed.text()).toContain(label);
    const markdown = mount(MarkdownContent, {
      props: {
        content:
          "**加粗** <script>alert(1)</script> [危险](javascript:alert(1))",
      },
    });
    expect(markdown.get("strong").text()).toBe("加粗");
    expect(markdown.find("script").exists()).toBe(false);
    expect(markdown.find("a").exists()).toBe(false);
  });
});
