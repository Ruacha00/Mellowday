import { useEffect, useRef, type ReactNode } from "react";

import type { ChatMessage } from "../services/conversationApi";
import type { LiveConversationEvent } from "../services/liveEvents";

interface ConversationSurfaceProps {
  conversationId: string;
  conversationTitle: string;
  latestLiveEvent: LiveConversationEvent | null;
  loadState: "loading" | "ready" | "error";
  messages: ChatMessage[];
}

type ConversationEventState = "pending" | "success" | "failure" | "neutral";

interface ConversationEventCardProps {
  detail: string;
  label: string;
  state?: ConversationEventState;
  title: string;
}

type MarkdownBlock =
  | { kind: "code"; content: string; language: string | null }
  | { kind: "heading"; content: string }
  | { kind: "list"; items: string[]; ordered: boolean }
  | { kind: "paragraph"; content: string }
  | { kind: "quote"; content: string };

export function ConversationSurface({
  conversationId,
  conversationTitle,
  latestLiveEvent,
  loadState,
  messages,
}: ConversationSurfaceProps) {
  const transcript = useRef<HTMLOListElement>(null);
  const liveMessageIndex = matchingLiveMessageIndex(messages, latestLiveEvent);

  useEffect(() => {
    if (loadState === "ready" && transcript.current !== null) {
      transcript.current.scrollTop = transcript.current.scrollHeight;
    }
  }, [conversationId, loadState, messages.length]);

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
        {messages.length === 0 && loadState === "ready" ? (
          <li className="empty-transcript">还没有已存消息。可以从此刻开始。</li>
        ) : null}
        {messages.map((message, index) => {
          const liveSource = index === liveMessageIndex
            ? latestLiveEvent?.kind ?? null
            : null;
          return liveSource === "reminder" ? (
            <ConversationEventCard
              detail={message.content}
              key={`stored-${index}`}
              label="提醒"
              title="已送达的提醒"
            />
          ) : (
            <TranscriptMessage
              key={`stored-${index}`}
              message={message}
              source={liveSource}
            />
          );
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

function TranscriptMessage({
  message,
  source,
}: {
  message: ChatMessage;
  source: LiveConversationEvent["kind"] | null;
}) {
  return (
    <li
      className={`message message-${message.role}`}
      data-role={message.role}
      data-source={source ?? undefined}
    >
      <div className="message-meta">
        <strong>{message.role === "user" ? "你" : "Mellowday"}</strong>
        {source === "proactive_chat" ? (
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

export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="message-body">
      {parseMarkdownBlocks(content).map((block, index) => {
        if (block.kind === "code") {
          return (
            <pre key={index}>
              <code
                className={block.language === null
                  ? undefined
                  : `language-${block.language}`}
              >
                {block.content}
              </code>
            </pre>
          );
        }
        if (block.kind === "heading") {
          return <h3 key={index}>{renderInlineMarkdown(block.content)}</h3>;
        }
        if (block.kind === "quote") {
          return <blockquote key={index}>{renderInlineMarkdown(block.content)}</blockquote>;
        }
        if (block.kind === "list") {
          const items = block.items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInlineMarkdown(item)}</li>
          ));
          return block.ordered
            ? <ol key={index}>{items}</ol>
            : <ul key={index}>{items}</ul>;
        }
        return <p key={index}>{renderInlineMarkdown(block.content)}</p>;
      })}
    </div>
  );
}

function matchingLiveMessageIndex(
  messages: ChatMessage[],
  event: LiveConversationEvent | null,
): number {
  if (event === null) {
    return -1;
  }
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === event.message.role &&
      message.content === event.message.content
    ) {
      return index;
    }
  }
  return -1;
}

function parseMarkdownBlocks(content: string): MarkdownBlock[] {
  const lines = content.replace(/\r\n?/gu, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (line.trim().length === 0) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```([^`]*)$/u);
    if (fence !== null) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/u.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      const language = fence[1].trim();
      blocks.push({
        kind: "code",
        content: codeLines.join("\n"),
        language: /^[a-z0-9_+-]+$/iu.test(language)
          ? language.toLowerCase()
          : null,
      });
      continue;
    }

    const heading = line.match(/^\s*#{1,6}\s+(.+)$/u);
    if (heading !== null) {
      blocks.push({ kind: "heading", content: heading[1].trim() });
      index += 1;
      continue;
    }

    if (/^\s*>\s?/u.test(line)) {
      const quoteLines: string[] = [];
      while (index < lines.length && /^\s*>\s?/u.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/u, ""));
        index += 1;
      }
      blocks.push({ kind: "quote", content: quoteLines.join("\n") });
      continue;
    }

    const unordered = /^\s*[-*+]\s+/u.test(line);
    const ordered = /^\s*\d+[.)]\s+/u.test(line);
    if (unordered || ordered) {
      const items: string[] = [];
      const itemPattern = ordered ? /^\s*\d+[.)]\s+/u : /^\s*[-*+]\s+/u;
      while (index < lines.length && itemPattern.test(lines[index])) {
        items.push(lines[index].replace(itemPattern, ""));
        index += 1;
      }
      blocks.push({ kind: "list", items, ordered });
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim().length > 0 &&
      !startsMarkdownBlock(lines[index])
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: "paragraph", content: paragraphLines.join("\n") });
  }

  return blocks.length === 0 ? [{ kind: "paragraph", content: "" }] : blocks;
}

function startsMarkdownBlock(line: string): boolean {
  return (
    /^\s*```/u.test(line) ||
    /^\s*#{1,6}\s+/u.test(line) ||
    /^\s*>\s?/u.test(line) ||
    /^\s*[-*+]\s+/u.test(line) ||
    /^\s*\d+[.)]\s+/u.test(line)
  );
}

function renderInlineMarkdown(content: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/gu;
  let cursor = 0;

  for (const match of content.matchAll(pattern)) {
    const start = match.index;
    if (start > cursor) {
      tokens.push(content.slice(cursor, start));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      tokens.push(<code key={start}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      tokens.push(<strong key={start}>{token.slice(2, -2)}</strong>);
    } else {
      const separator = token.lastIndexOf("](");
      const label = token.slice(1, separator);
      const href = token.slice(separator + 2, -1);
      tokens.push(isSafeLink(href)
        ? <a href={href} key={start} rel="noreferrer">{label}</a>
        : label);
    }
    cursor = start + token.length;
  }
  if (cursor < content.length) {
    tokens.push(content.slice(cursor));
  }
  return tokens;
}

function isSafeLink(href: string): boolean {
  return /^(https?:|mailto:|\/|#)/iu.test(href);
}
