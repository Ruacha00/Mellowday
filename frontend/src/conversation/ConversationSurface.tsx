import type { ChatMessage } from "../services/conversationApi";
import type { LiveConversationEvent } from "../services/liveEvents";

interface ConversationSurfaceProps {
  latestLiveEvent: LiveConversationEvent | null;
  loadState: "loading" | "ready" | "error";
  messages: ChatMessage[];
}

export function ConversationSurface({
  latestLiveEvent,
  loadState,
  messages,
}: ConversationSurfaceProps) {
  return (
    <section aria-labelledby="conversation-title" className="conversation-workspace">
      <div className="conversation-heading">
        <div>
          <span>对话</span>
          <h2 id="conversation-title">今天，慢慢来</h2>
        </div>
        <span className="load-state">
          {loadState === "loading" && "正在加载已存会话…"}
          {loadState === "ready" && "已加载存储会话。"}
          {loadState === "error" && "无法读取存储会话。"}
        </span>
      </div>
      <p aria-atomic="true" aria-live="polite" className="visually-hidden">
        {latestLiveEvent === null
          ? ""
          : `${liveSourceLabel(latestLiveEvent.kind)}：${latestLiveEvent.message.content}`}
      </p>
      <ol aria-label="会话记录" className="transcript">
        {messages.length === 0 && loadState !== "loading" ? (
          <li className="empty-transcript">还没有已存消息。可以从此刻开始。</li>
        ) : null}
        {messages.map((message, index) => (
          <TranscriptMessage key={`stored-${index}`} message={message} />
        ))}
      </ol>
      <div className="composer-preview" aria-label="消息编辑器占位">
        <span aria-hidden="true">＋</span>
        <span>输入消息…</span>
        <button disabled type="button">发送</button>
      </div>
    </section>
  );
}

function TranscriptMessage({ message }: { message: ChatMessage }) {
  return (
    <li className={`message message-${message.role}`} data-role={message.role}>
      <div className="message-meta">
        <strong>{message.role === "user" ? "你" : "Mellowday"}</strong>
      </div>
      <p>{message.content}</p>
    </li>
  );
}

function liveSourceLabel(kind: LiveConversationEvent["kind"]): string {
  return kind === "reminder" ? "提醒" : "主动聊天";
}
