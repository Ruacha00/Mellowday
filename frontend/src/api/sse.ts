import type { RuntimeEvent } from "./types";

export class StreamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamError";
  }
}

/** A turn ends only at the protocol's done event, including post-answer learning. */
export async function readEventStream(
  response: Response,
  onEvent: (event: RuntimeEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.ok) {
    let message = `对话请求失败（HTTP ${response.status}）`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message += `：${data.detail}`;
    } catch {
      /* The status remains useful for non-JSON errors. */
    }
    throw new StreamError(message);
  }
  if (
    !response.headers.get("content-type")?.includes("text/event-stream") ||
    !response.body
  ) {
    throw new StreamError("服务未返回有效的对话事件流。");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let data: string[] = [];
  let eventName = "";
  let completed = false;
  const abort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", abort, { once: true });
  const assertActive = () => {
    if (signal?.aborted) throw new DOMException("本轮已停止", "AbortError");
  };
  const dispatch = () => {
    if (!data.length) {
      eventName = "";
      return;
    }
    let value: unknown;
    try {
      value = JSON.parse(data.join("\n"));
    } catch {
      throw new StreamError("对话事件格式无效，本轮已中断。");
    }
    data = [];
    if (
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      typeof (value as RuntimeEvent).type !== "string" ||
      !(value as RuntimeEvent).type
    ) {
      throw new StreamError("对话事件缺少有效类型，本轮已中断。");
    }
    const event = value as RuntimeEvent;
    if (eventName && eventName !== event.type && eventName !== "message") {
      throw new StreamError("对话事件类型不一致，本轮已中断。");
    }
    eventName = "";
    onEvent(event);
    completed = event.type === "done";
  };
  const line = (value: string) => {
    if (!value) {
      dispatch();
      return;
    }
    if (value.startsWith(":")) return;
    const colon = value.indexOf(":");
    const field = colon < 0 ? value : value.slice(0, colon);
    let content = colon < 0 ? "" : value.slice(colon + 1);
    if (content.startsWith(" ")) content = content.slice(1);
    if (field === "data") data.push(content);
    else if (field === "event") eventName = content;
  };
  const consume = (final: boolean) => {
    while (!completed) {
      const boundary = buffer.search(/[\r\n]/);
      if (boundary < 0) break;
      if (!final && buffer[boundary] === "\r" && boundary === buffer.length - 1)
        break;
      const width =
        buffer[boundary] === "\r" && buffer[boundary + 1] === "\n" ? 2 : 1;
      const current = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + width);
      line(current);
    }
    if (final && !completed) {
      if (buffer) line(buffer);
      buffer = "";
      if (data.length) dispatch();
    }
  };
  try {
    assertActive();
    while (!completed) {
      const result = await reader.read();
      assertActive();
      buffer += decoder.decode(result.value, { stream: !result.done });
      consume(result.done);
      if (result.done) break;
    }
    if (!completed)
      throw new StreamError("连接提前结束，本轮已中断；不会自动重发。");
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function postChatStream(
  sessionId: string | null,
  message: string,
  onEvent: (event: RuntimeEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  await readEventStream(response, onEvent, signal);
}
