import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type { ConversationSummary } from "../services/conversationApi";
import { recentConversationTitle } from "./recentConversations";

interface RecentConversationProps {
  activeConversationId: string;
  onDelete: (summary: ConversationSummary) => Promise<void>;
  onRename: (summary: ConversationSummary, title: string) => Promise<void>;
  onSelect: (conversationId: string) => void;
  summaries: ConversationSummary[];
}

export function RecentConversationList({
  activeConversationId,
  onDelete,
  onRename,
  onSelect,
  summaries,
}: RecentConversationProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<{ id: string; message: string } | null>(null);
  const actionTrigger = useRef<HTMLButtonElement | null>(null);
  const emptyRecent = useRef<HTMLParagraphElement | null>(null);
  const selectButtons = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    const existingIds = new Set(summaries.map((summary) => summary.conversationId));
    if (editingId !== null && !existingIds.has(editingId)) setEditingId(null);
    if (deletingId !== null && !existingIds.has(deletingId)) setDeletingId(null);
  }, [deletingId, editingId, summaries]);

  const restoreActionFocus = () => {
    window.requestAnimationFrame(() => actionTrigger.current?.focus());
  };

  const beginEdit = (summary: ConversationSummary, trigger: HTMLButtonElement) => {
    actionTrigger.current = trigger;
    setDeletingId(null);
    setEditingId(summary.conversationId);
    setTitleDraft(recentConversationTitle(summary));
    setError(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setError(null);
    restoreActionFocus();
  };

  const submitRename = async (
    event: FormEvent<HTMLFormElement>,
    summary: ConversationSummary,
  ) => {
    event.preventDefault();
    const title = titleDraft.trim();
    if (!title) {
      setError({ id: summary.conversationId, message: "标题不能为空。" });
      return;
    }
    setBusyId(summary.conversationId);
    setError(null);
    try {
      await onRename(summary, title);
      setEditingId(null);
      restoreActionFocus();
    } catch {
      setError({ id: summary.conversationId, message: "标题保存失败，请重试。" });
    } finally {
      setBusyId(null);
    }
  };

  const beginDelete = (summary: ConversationSummary, trigger: HTMLButtonElement) => {
    actionTrigger.current = trigger;
    setEditingId(null);
    setDeletingId(summary.conversationId);
    setError(null);
  };

  const cancelDelete = () => {
    setDeletingId(null);
    setError(null);
    restoreActionFocus();
  };

  const confirmDelete = async (summary: ConversationSummary) => {
    const deletedIndex = summaries.findIndex(
      (item) => item.conversationId === summary.conversationId,
    );
    const remaining = summaries.filter(
      (item) => item.conversationId !== summary.conversationId,
    );
    const focusTarget = remaining[Math.min(deletedIndex, remaining.length - 1)]
      ?.conversationId ?? null;
    setBusyId(summary.conversationId);
    setError(null);
    try {
      await onDelete(summary);
      setDeletingId(null);
      window.requestAnimationFrame(() => {
        if (focusTarget === null) {
          emptyRecent.current?.focus();
        } else {
          selectButtons.current.get(focusTarget)?.focus();
        }
      });
    } catch {
      setError({ id: summary.conversationId, message: "对话删除失败，请重试。" });
    } finally {
      setBusyId(null);
    }
  };

  if (summaries.length === 0) {
    return (
      <p className="empty-recent" ref={emptyRecent} tabIndex={-1}>
        还没有最近对话
      </p>
    );
  }
  return (
    <ol className="recent-list">
      {summaries.map((summary) => {
        const title = recentConversationTitle(summary);
        const isBusy = busyId === summary.conversationId;
        return (
          <li className="recent-conversation-item" key={summary.conversationId}>
            <div className="recent-conversation-row">
              <button
                aria-current={summary.conversationId === activeConversationId ? "true" : undefined}
                className="recent-conversation-select"
                disabled={isBusy}
                onClick={() => onSelect(summary.conversationId)}
                ref={(node) => {
                  if (node === null) {
                    selectButtons.current.delete(summary.conversationId);
                  } else {
                    selectButtons.current.set(summary.conversationId, node);
                  }
                }}
                type="button"
              >
                <strong>{title}</strong>
                <span>{summary.messageCount} 条 · {formatActivity(summary.updatedAt)}</span>
              </button>
              <div className="recent-conversation-actions">
                <button
                  aria-label={`编辑“${title}”的标题`}
                  disabled={isBusy}
                  onClick={(event) => beginEdit(summary, event.currentTarget)}
                  type="button"
                >
                  编辑
                </button>
                <button
                  aria-label={`删除“${title}”`}
                  disabled={isBusy}
                  onClick={(event) => beginDelete(summary, event.currentTarget)}
                  type="button"
                >
                  删除
                </button>
              </div>
            </div>
            {editingId === summary.conversationId ? (
              <form className="recent-conversation-editor" onSubmit={(event) => void submitRename(event, summary)}>
                <label>
                  <span>对话标题</span>
                  <input
                    aria-label="对话标题"
                    autoFocus
                    disabled={isBusy}
                    maxLength={120}
                    onChange={(event) => setTitleDraft(event.currentTarget.value)}
                    value={titleDraft}
                  />
                </label>
                <div>
                  <button disabled={isBusy} onClick={cancelEdit} type="button">取消编辑</button>
                  <button disabled={isBusy || !titleDraft.trim()} type="submit">保存标题</button>
                </div>
              </form>
            ) : null}
            {deletingId === summary.conversationId ? (
              <div aria-label={`删除“${title}”`} className="recent-conversation-delete" role="group">
                <span>删除这个对话？</span>
                <div>
                  <button disabled={isBusy} onClick={cancelDelete} type="button">取消删除</button>
                  <button
                    aria-label={`确认删除“${title}”`}
                    className="recent-delete-confirm"
                    disabled={isBusy}
                    onClick={() => void confirmDelete(summary)}
                    type="button"
                  >
                    {isBusy ? "正在删除…" : "确认删除"}
                  </button>
                </div>
              </div>
            ) : null}
            {error?.id === summary.conversationId ? (
              <p className="recent-conversation-error" role="alert">{error.message}</p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

interface RecentConversationDrawerProps extends RecentConversationProps {
  onClose: () => void;
}

export function RecentConversationDrawer({
  activeConversationId,
  onClose,
  onDelete,
  onRename,
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
          onDelete={onDelete}
          onRename={onRename}
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
