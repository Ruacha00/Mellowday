import {
  useEffect,
  useRef,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import type {
  ChatMessage,
  ConfirmationDecision,
  PendingConfirmation,
} from "../services/conversationApi";
import { MarkdownContent } from "./MarkdownContent";

export type ConversationEventState =
  | "pending"
  | "success"
  | "failure"
  | "cancelled"
  | "neutral";

export type ConversationConfirmationPhase =
  | "awaiting"
  | "deciding"
  | "accepted"
  | "cancelled"
  | "decision_failure"
  | "execution_failure";

export interface ConversationConfirmationView {
  confirmation: PendingConfirmation;
  phase: ConversationConfirmationPhase;
}

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
  confirmations?: ConversationConfirmationView[];
  conversationId: string;
  conversationTitle: string;
  draft?: string;
  entries: ConversationEntry[];
  loadState: "loading" | "ready" | "error";
  onConfirmationDecision?: (
    confirmationId: string,
    decision: ConfirmationDecision,
  ) => void;
  onDraftChange?: (value: string) => void;
  onSend?: () => void;
  sending?: boolean;
}

interface ConversationEventCardProps {
  detail: string;
  label: string;
  state?: ConversationEventState;
  title: string;
}

export function ConversationSurface({
  confirmations = [],
  conversationId,
  conversationTitle,
  draft = "",
  entries,
  loadState,
  onConfirmationDecision = () => undefined,
  onDraftChange = () => undefined,
  onSend = () => undefined,
  sending = false,
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
        {confirmations.map((confirmation) => (
          <ConversationConfirmationCard
            key={confirmation.confirmation.id}
            onDecision={onConfirmationDecision}
            view={confirmation}
          />
        ))}
      </ol>
      <ConversationComposer
        busy={sending}
        onChange={onDraftChange}
        onSend={onSend}
        value={draft}
      />
    </section>
  );
}

interface ConversationComposerProps {
  busy: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  value: string;
}

function ConversationComposer({
  busy,
  onChange,
  onSend,
  value,
}: ConversationComposerProps) {
  const composing = useRef(false);
  const canSend = !busy && value.trim().length > 0;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canSend) {
      onSend();
    }
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      composing.current
    ) {
      return;
    }
    event.preventDefault();
    if (canSend) {
      onSend();
    }
  };

  return (
    <form aria-label="消息编辑器" className="composer" onSubmit={submit}>
      <textarea
        aria-label="消息"
        onChange={(event) => onChange(event.currentTarget.value)}
        onCompositionEnd={() => {
          composing.current = false;
        }}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onKeyDown={handleKeyDown}
        placeholder="输入消息…"
        rows={1}
        value={value}
      />
      <button aria-label="发送消息" disabled={!canSend} type="submit">
        {busy ? "发送中" : "发送"}
      </button>
    </form>
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

function ConversationConfirmationCard({
  onDecision,
  view,
}: {
  onDecision: (
    confirmationId: string,
    decision: ConfirmationDecision,
  ) => void;
  view: ConversationConfirmationView;
}) {
  const card = useRef<HTMLLIElement>(null);
  const previousPhase = useRef(view.phase);
  const presentation = confirmationPresentation(view.phase);
  const canDecide =
    view.phase === "awaiting" || view.phase === "decision_failure";

  useEffect(() => {
    if (previousPhase.current === "deciding" && view.phase !== "deciding") {
      card.current?.focus();
    }
    previousPhase.current = view.phase;
  }, [view.phase]);

  return (
    <li
      aria-label="操作确认"
      className="conversation-event-card confirmation-event-card"
      data-state={presentation.state}
      ref={card}
      role="group"
      tabIndex={-1}
    >
      <div className="event-card-label">操作确认</div>
      <div className="event-card-content">
        <strong>{presentation.title}</strong>
        <p>
          需要确认的操作：<code>{view.confirmation.binding.tool}</code>
        </p>
        {canDecide ? (
          <div className="confirmation-actions">
            <button
              onClick={() => onDecision(view.confirmation.id, "reject")}
              type="button"
            >
              取消操作
            </button>
            <button
              className="confirmation-accept"
              onClick={() => onDecision(view.confirmation.id, "accept")}
              type="button"
            >
              确认执行
            </button>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function confirmationPresentation(phase: ConversationConfirmationPhase): {
  state: ConversationEventState;
  title: string;
} {
  switch (phase) {
    case "awaiting":
      return { state: "pending", title: "等待你的确认" };
    case "deciding":
      return { state: "pending", title: "正在处理确认" };
    case "accepted":
      return { state: "success", title: "操作已完成" };
    case "cancelled":
      return { state: "cancelled", title: "已取消操作" };
    case "decision_failure":
      return { state: "failure", title: "确认处理失败" };
    case "execution_failure":
      return { state: "failure", title: "操作执行失败" };
  }
}
