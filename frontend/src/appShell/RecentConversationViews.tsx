import {
  useEffect,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type { ConversationSummary } from "../services/conversationApi";
import { recentConversationTitle } from "./recentConversations";

interface RecentConversationProps {
  activeConversationId: string;
  onSelect: (conversationId: string) => void;
  summaries: ConversationSummary[];
}

export function RecentConversationList({
  activeConversationId,
  onSelect,
  summaries,
}: RecentConversationProps) {
  if (summaries.length === 0) {
    return <p className="empty-recent">还没有最近对话</p>;
  }
  return (
    <ol className="recent-list">
      {summaries.map((summary) => (
        <li key={summary.conversationId}>
          <button
            aria-current={summary.conversationId === activeConversationId ? "true" : undefined}
            onClick={() => onSelect(summary.conversationId)}
            type="button"
          >
            <strong>{recentConversationTitle(summary)}</strong>
            <span>{summary.messageCount} 条 · {formatActivity(summary.updatedAt)}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

interface RecentConversationDrawerProps extends RecentConversationProps {
  onClose: () => void;
}

export function RecentConversationDrawer({
  activeConversationId,
  onClose,
  onSelect,
  summaries,
}: RecentConversationDrawerProps) {
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButton.current?.focus();
  }, []);

  const containFocus = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab" || dialog.current === null) {
      return;
    }
    const focusable = [...dialog.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="drawer-layer">
      <div aria-hidden="true" className="drawer-backdrop" />
      <div
        aria-labelledby="recent-drawer-title"
        aria-modal="true"
        className="recent-drawer"
        onKeyDown={containFocus}
        ref={dialog}
        role="dialog"
      >
        <header>
          <h2 id="recent-drawer-title">最近对话</h2>
          <button
            aria-label="关闭最近对话"
            className="drawer-close"
            onClick={onClose}
            ref={closeButton}
            type="button"
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>
        <RecentConversationList
          activeConversationId={activeConversationId}
          onSelect={onSelect}
          summaries={summaries}
        />
      </div>
    </div>
  );
}

function formatActivity(timestamp: number): string {
  if (!Number.isFinite(timestamp) || timestamp <= 0) {
    return "时间未记录";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(new Date(timestamp * 1_000));
}
