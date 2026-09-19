import { afterEach, describe, expect, it, vi } from "vitest";
import { readEventStream, postChatStream } from "../src/api/sse";
import type { RuntimeEvent } from "../src/api/types";

function responseFor(text: string, bytewise = false) {
  const bytes = new TextEncoder().encode(text);
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        if (bytewise)
          for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        else controller.enqueue(bytes);
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
  );
}
afterEach(() => vi.unstubAllGlobals());

describe("POST event stream", () => {
  it("reassembles Chinese UTF-8 and CRLF split at every byte, multi-line data and an unterminated final done", async () => {
    const events: RuntimeEvent[] = [];
    await readEventStream(
      responseFor(
        ': 心跳\r\nevent: text_delta\r\ndata: {"type":"text_delta",\r\ndata: "text":"你好🌿"}\r\n\r\nid: ignored\nevent: turn_end\ndata:{"type":"turn_end"}\n\nevent: done\ndata: {"type":"done"}',
        true,
      ),
      (event) => events.push(event),
    );
    expect(events).toEqual([
      { type: "text_delta", text: "你好🌿" },
      { type: "turn_end" },
      { type: "done" },
    ]);
  });

  it("continues after turn_end to read learning and releases the reader once done arrives", async () => {
    const cancelled = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data:{"type":"turn_end"}\n\ndata:{"type":"skill_candidate_applied","skill":"偏好"}\n\ndata:{"type":"done"}\n\n',
          ),
        );
      },
      cancel: cancelled,
    });
    const observed: string[] = [];
    await readEventStream(
      new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
      (event) => observed.push(event.type),
    );
    expect(observed).toEqual(["turn_end", "skill_candidate_applied", "done"]);
    expect(cancelled).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it.each([
    ['data:{"type":"turn_end"}\n\n', "连接提前结束"],
    ["data:not-json\n\n", "格式无效"],
    ['data:{"text":"hello"}\n\n', "缺少有效类型"],
    ['event: text_delta\ndata:{"type":"done"}\n\n', "类型不一致"],
  ])(
    "rejects incomplete or malformed events without retry: %s",
    async (frame, expected) => {
      await expect(
        readEventStream(responseFor(frame), vi.fn()),
      ).rejects.toThrow(expected);
    },
  );

  it("cancels an idle reader when the request is stopped", async () => {
    const cancelled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel: cancelled });
    const controller = new AbortController();
    const pending = readEventStream(
      new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
      vi.fn(),
      controller.signal,
    );
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(cancelled).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it("reports HTTP JSON errors and rejects an HTML success fallback", async () => {
    await expect(
      readEventStream(
        new Response('{"detail":"会话不存在"}', { status: 404 }),
        vi.fn(),
      ),
    ).rejects.toThrow("会话不存在");
    await expect(
      readEventStream(
        new Response("<html>app</html>", {
          headers: { "Content-Type": "text/html" },
        }),
        vi.fn(),
      ),
    ).rejects.toThrow("有效的对话事件流");
  });

  it("posts the session and message exactly once and passes the cancellation signal", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(responseFor('data:{"type":"done"}\n\n'));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await postChatStream("session-one", "你好", vi.fn(), controller.signal);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      "/api/chat",
      expect.objectContaining({
        method: "POST",
        signal: controller.signal,
        body: '{"session_id":"session-one","message":"你好"}',
      }),
    );
  });
});
