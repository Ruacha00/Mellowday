import { useEffect, useRef } from "react";

import type { ChatMessage } from "../services/conversationApi";
import { MarkdownContent } from "./MarkdownContent";

export type ConversationEventState =
  | "pending"
  | "success"
  | "failure"
  | "neutral";

export type ConversationEntry =
  | {
      id: string;
      kind: "message";
      message: ChatMessage;
    }
  | {
      id: string;
      kind: "event";
      detail: string;
      label: string;
      state?: ConversationEventState;
      title: string;
    };

interface ConversationSurfaceProps {
  conversationId: string;
  conversationTitle: string;
  entries: ConversationEntry[];
  loadState: "loading" | "ready" | "error";
}

interface ConversationEventCardProps {
  detail: string;
  label: string;
  state?: ConversationEventState;
  title: string;
}

export function ConversationSurface({
  conversationId,
  conversationTitle,
  entries,
  loadState,
}: ConversationSurfaceProps) {
  const transcript = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (loadState === "ready" && transcript.current !== null) {
      transcript.current.scrollTop = transcript.current.scrollHeight;
    }
  }, [conversationId, entries.length, loadState]);

  return (
    <section aria-labelledby="conversation-title" className="conversation-workspace">
      <div className="conversation-heading">
        <div>
          <span>对话</span>
          <h2 id="conversation-title">{conversationTitle}</h2>
        </div>
        <span className="load-state">
          {loadState === "loading" && "正在加载已存会话…"}
          {loadState === "ready" && "已加载存储会话。"}
          {loadState === "error" && "会话历史暂时不可用"}
        </span>
      </div>
      <ol
        aria-busy={loadState === "loading"}
        aria-label="会话记录"
        className="transcript"
        ref={transcript}
      >
        {loadState === "error" ? (
          <ConversationEventCard
            detail="请稍后重试。现有内容没有被更改。"
            label="会话历史"
            state="failure"
            title="无法读取存储会话"
          />
        ) : null}
        {entries.length === 0 && loadState === "ready" ? (
          <li className="empty-transcript">还没有已存消息。可以从此刻开始。</li>
        ) : null}
        {entries.map((entry) => {
          if (entry.kind === "event") {
            return <ConversationEventCard key={entry.id} {...entry} />;
          }
          if (entry.message.source === "reminder") {
            return (
              <ConversationEventCard
                detail={entry.message.content}
                key={entry.id}
                label="提醒"
                title="已送达的提醒"
              />
            );
          }
          return <TranscriptMessage key={entry.id} message={entry.message} />;
        })}
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
    <li
      className={`message message-${message.role}`}
      data-role={message.role}
      data-source={message.source ?? undefined}
    >
      <div className="message-meta">
        <strong>{message.role === "user" ? "你" : "Mellowday"}</strong>
        {message.source === "proactive_chat" ? (
          <span className="message-source">主动聊天</span>
        ) : null}
      </div>
      <MarkdownContent content={message.content} />
    </li>
  );
}

export function ConversationEventCard({
  detail,
  label,
  state = "neutral",
  title,
}: ConversationEventCardProps) {
  return (
    <li className="conversation-event-card" data-state={state}>
      <div className="event-card-label">{label}</div>
      <div className="event-card-content">
        <strong>{title}</strong>
        <MarkdownContent content={detail} />
      </div>
    </li>
  );
}
