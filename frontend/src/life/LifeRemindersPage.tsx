import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";

import { LatestRequest } from "../services/requestLifecycle";
import type {
  Reminder,
  ReminderDeliveryState,
  ReminderDraft,
  ReminderService,
} from "../services/reminderApi";

interface LifeRemindersPageProps {
  service: ReminderService;
}

interface EditorDraft {
  message: string;
  dueAt: string;
  taskId: string;
  conversationId: string;
}

interface DeleteConfirmation {
  reminder: Reminder;
  confirmation: Awaited<
    ReturnType<ReminderService["requestDeleteConfirmation"]>
  >;
}

const emptyDraft: EditorDraft = {
  message: "",
  dueAt: "",
  taskId: "",
  conversationId: "main",
};

const deliveryStateLabels: Record<ReminderDeliveryState, string> = {
  scheduled: "已安排",
  delivering: "正在投递",
  delivered: "已投递",
  failed: "投递失败",
  dismissed: "已忽略",
  cancelled: "已取消",
};

function toLocalInputValue(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toDueAt(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function formatDueAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatRecordedAt(value: number | null): string {
  return value === null ? "无" : formatDueAt(new Date(value * 1_000).toISOString());
}

export function LifeRemindersPage({ service }: LifeRemindersPageProps) {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [draft, setDraft] = useState<EditorDraft>(emptyDraft);
  const [editingReminderId, setEditingReminderId] = useState<string | null>(null);
  const [busyReminderId, setBusyReminderId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<{
    reminderId: string;
    state: "loading" | "ready" | "error";
    reminder: Reminder | null;
  } | null>(null);
  const [confirmationError, setConfirmationError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<DeleteConfirmation | null>(
    null,
  );
  const loadRequest = useRef(new LatestRequest());
  const detailRequest = useRef(new LatestRequest());
  const mounted = useRef(false);
  const messageInput = useRef<HTMLInputElement>(null);
  const dueAtInput = useRef<HTMLInputElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const confirmDeleteButton = useRef<HTMLButtonElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  const loadReminders = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    void loadRequest.current
      .run((signal) => service.listReminders(signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setReminders(result.value);
          setDetail((current) => {
            if (current === null || current.state !== "ready") {
              return current;
            }
            const latest = result.value.find(
              (reminder) => reminder.id === current.reminderId,
            );
            return latest === undefined
              ? null
              : { ...current, reminder: latest };
          });
          setLoadState("ready");
        }
      })
      .catch(() => {
        if (mounted.current) {
          setLoadState("error");
        }
      });
  }, [service]);

  useEffect(() => {
    mounted.current = true;
    loadReminders(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      detailRequest.current.cancel();
    };
  }, [loadReminders]);

  useEffect(() => {
    if (pendingDelete !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [pendingDelete]);

  const resetEditor = () => {
    setDraft(emptyDraft);
    setEditingReminderId(null);
  };

  const editReminder = (reminder: Reminder) => {
    setDraft({
      message: reminder.message,
      dueAt: toLocalInputValue(reminder.dueAt),
      taskId: reminder.taskId ?? "",
      conversationId: reminder.conversationId,
    });
    setEditingReminderId(reminder.id);
    window.requestAnimationFrame(() => messageInput.current?.focus());
  };

  const saveReminder = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = draft.message.trim();
    if (message.length === 0) {
      setNotice("请输入提醒内容。");
      messageInput.current?.focus();
      return;
    }
    const dueAt = toDueAt(draft.dueAt);
    if (dueAt === null) {
      setNotice("请选择有效的提醒时间。");
      dueAtInput.current?.focus();
      return;
    }
    const payload: ReminderDraft = {
      message,
      dueAt,
      taskId: draft.taskId.trim() || null,
      conversationId: draft.conversationId,
    };
    setSubmitting(true);
    setNotice("");
    try {
      if (editingReminderId === null) {
        await service.createReminder(payload);
        if (!mounted.current) {
          return;
        }
        setNotice("提醒已添加。");
      } else {
        await service.updateReminder(editingReminderId, payload);
        if (!mounted.current) {
          return;
        }
        setNotice("提醒已保存并重新安排。");
      }
      resetEditor();
      loadReminders(false);
    } catch {
      if (mounted.current) {
        setNotice(editingReminderId === null ? "提醒添加失败。" : "提醒保存失败。");
      }
    } finally {
      if (mounted.current) {
        setSubmitting(false);
      }
    }
  };

  const inspectReminder = (reminder: Reminder) => {
    if (detail?.reminderId === reminder.id) {
      detailRequest.current.cancel();
      setDetail(null);
      return;
    }
    setDetail({ reminderId: reminder.id, state: "loading", reminder: null });
    void detailRequest.current
      .run((signal) => service.getReminder(reminder.id, signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setDetail({
            reminderId: reminder.id,
            state: "ready",
            reminder: result.value,
          });
        }
      })
      .catch(() => {
        if (mounted.current) {
          setDetail({ reminderId: reminder.id, state: "error", reminder: null });
        }
      });
  };

  const changeDeliveryState = async (
    reminder: Reminder,
    operation: "cancel" | "dismiss",
  ) => {
    setBusyReminderId(reminder.id);
    setNotice("");
    try {
      if (operation === "cancel") {
        await service.cancelReminder(reminder.id);
      } else {
        await service.dismissReminder(reminder.id);
      }
      if (!mounted.current) {
        return;
      }
      setNotice(operation === "cancel" ? "提醒已取消。" : "提醒已忽略。");
      loadReminders(false);
    } catch {
      if (mounted.current) {
        setNotice(operation === "cancel" ? "提醒取消失败。" : "提醒忽略失败。");
      }
    } finally {
      if (mounted.current) {
        setBusyReminderId(null);
      }
    }
  };

  const requestDelete = async (
    reminder: Reminder,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    deleteTrigger.current = event.currentTarget;
    setBusyReminderId(reminder.id);
    setNotice("正在准备删除确认…");
    setConfirmationError("");
    try {
      const confirmation = await service.requestDeleteConfirmation(reminder.id);
      if (!mounted.current) {
        return;
      }
      setPendingDelete({ reminder, confirmation });
      setNotice("");
    } catch {
      if (mounted.current) {
        setNotice("无法准备提醒删除确认。");
      }
    } finally {
      if (mounted.current) {
        setBusyReminderId(null);
      }
    }
  };

  const restoreDeleteFocus = () => {
    window.requestAnimationFrame(() => deleteTrigger.current?.focus());
  };

  const cancelDelete = async () => {
    const current = pendingDelete;
    if (current === null) {
      return;
    }
    setBusyReminderId(current.reminder.id);
    setConfirmationError("");
    try {
      await service.decideDelete(
        current.reminder.id,
        current.confirmation,
        "reject",
      );
      if (!mounted.current) {
        return;
      }
      setPendingDelete(null);
      setNotice("已取消删除提醒。");
      restoreDeleteFocus();
    } catch {
      if (mounted.current) {
        setConfirmationError("取消删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyReminderId(null);
      }
    }
  };

  const confirmDelete = async () => {
    const current = pendingDelete;
    if (current === null) {
      return;
    }
    setBusyReminderId(current.reminder.id);
    setConfirmationError("");
    try {
      const result = await service.decideDelete(
        current.reminder.id,
        current.confirmation,
        "accept",
      );
      if (!result.ok) {
        throw new Error("Reminder deletion was rejected");
      }
      if (!mounted.current) {
        return;
      }
      setPendingDelete(null);
      setNotice("提醒已删除。");
      if (editingReminderId === current.reminder.id) {
        resetEditor();
      }
      if (detail?.reminderId === current.reminder.id) {
        setDetail(null);
      }
      loadReminders(false);
    } catch {
      if (mounted.current) {
        setConfirmationError("提醒删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyReminderId(null);
      }
    }
  };

  return (
    <div className="reminders-page">
      <section aria-labelledby="reminder-editor-title" className="reminder-editor">
        <div className="reminder-section-heading">
          <div>
            <span>提醒安排</span>
            <h2 id="reminder-editor-title">
              {editingReminderId === null ? "添加提醒" : "编辑提醒"}
            </h2>
          </div>
          {editingReminderId === null ? null : (
            <button className="quiet-button" onClick={resetEditor} type="button">
              取消编辑
            </button>
          )}
        </div>
        <form className="reminder-form" noValidate onSubmit={saveReminder}>
          <label>
            <span>提醒内容</span>
            <input
              autoComplete="off"
              onChange={(event) => setDraft({ ...draft, message: event.target.value })}
              ref={messageInput}
              type="text"
              value={draft.message}
            />
          </label>
          <label>
            <span>提醒时间</span>
            <input
              onChange={(event) => setDraft({ ...draft, dueAt: event.target.value })}
              ref={dueAtInput}
              type="datetime-local"
              value={draft.dueAt}
            />
          </label>
          <label>
            <span>关联任务 ID（可选）</span>
            <input
              autoComplete="off"
              onChange={(event) => setDraft({ ...draft, taskId: event.target.value })}
              type="text"
              value={draft.taskId}
            />
          </label>
          <button className="primary-button" disabled={submitting} type="submit">
            {submitting
              ? "正在保存…"
              : editingReminderId === null
                ? "添加提醒"
                : "保存提醒"}
          </button>
        </form>
      </section>

      <p
        aria-label="提醒状态"
        aria-live="polite"
        className="reminder-notice"
        role="status"
      >
        {notice}
      </p>

      <section aria-labelledby="reminder-list-title" className="reminder-list-section">
        <div className="reminder-section-heading">
          <div>
            <span>生活记录</span>
            <h2 id="reminder-list-title">提醒列表</h2>
          </div>
          {loadState === "ready" ? <span>{reminders.length} 项</span> : null}
        </div>
        {loadState === "loading" ? (
          <p className="reminder-state" role="status">正在加载提醒…</p>
        ) : loadState === "error" ? (
          <div className="reminder-state" role="alert">
            <p>提醒加载失败。</p>
            <button className="quiet-button" onClick={() => loadReminders(true)} type="button">
              重试
            </button>
          </div>
        ) : reminders.length === 0 ? (
          <p className="reminder-state">还没有提醒。</p>
        ) : (
          <div className="reminder-list">
            {reminders.map((reminder) => {
              const showingDetail = detail?.reminderId === reminder.id;
              return (
                <article
                  className="reminder-card"
                  data-delivery-state={reminder.deliveryState}
                  key={reminder.id}
                >
                  <div className="reminder-card-heading">
                    <h3>{reminder.message}</h3>
                    <span>{deliveryStateLabels[reminder.deliveryState]}</span>
                  </div>
                  <p className="reminder-due">提醒时间：{formatDueAt(reminder.dueAt)}</p>
                  <p>关联任务：{reminder.taskId ?? "无"}</p>
                  <div className="reminder-actions">
                    <button
                      aria-expanded={showingDetail}
                      aria-label={`${showingDetail ? "收起" : "查看"} ${reminder.message}`}
                      disabled={busyReminderId === reminder.id}
                      onClick={() => inspectReminder(reminder)}
                      type="button"
                    >
                      {showingDetail ? "收起详情" : "查看详情"}
                    </button>
                    <button
                      aria-label={`编辑 ${reminder.message}`}
                      disabled={busyReminderId === reminder.id}
                      onClick={() => editReminder(reminder)}
                      type="button"
                    >
                      编辑
                    </button>
                    {reminder.deliveryState === "scheduled"
                      || reminder.deliveryState === "delivering" ? (
                        <button
                          aria-label={`取消 ${reminder.message}`}
                          disabled={busyReminderId === reminder.id}
                          onClick={() => void changeDeliveryState(reminder, "cancel")}
                          type="button"
                        >
                          取消安排
                        </button>
                      ) : reminder.deliveryState === "delivered"
                        || reminder.deliveryState === "failed" ? (
                          <button
                            aria-label={`忽略 ${reminder.message}`}
                            disabled={busyReminderId === reminder.id}
                            onClick={() => void changeDeliveryState(reminder, "dismiss")}
                            type="button"
                          >
                            忽略
                          </button>
                        ) : null}
                    <button
                      aria-label={`删除 ${reminder.message}`}
                      disabled={busyReminderId === reminder.id}
                      onClick={(event) => void requestDelete(reminder, event)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                  {showingDetail ? (
                    <div className="reminder-details" aria-live="polite">
                      {detail.state === "loading" ? (
                        <p role="status">正在加载提醒详情…</p>
                      ) : detail.state === "error" ? (
                        <p role="alert">提醒详情加载失败。</p>
                      ) : detail.reminder === null ? null : (
                        <dl>
                          <div><dt>投递状态</dt><dd>{deliveryStateLabels[detail.reminder.deliveryState]}</dd></div>
                          <div><dt>提醒时间</dt><dd>{formatDueAt(detail.reminder.dueAt)}</dd></div>
                          <div><dt>投递会话</dt><dd>{detail.reminder.conversationId}</dd></div>
                          <div><dt>已投递时间</dt><dd>{formatRecordedAt(detail.reminder.deliveredAt)}</dd></div>
                          <div><dt>投递错误</dt><dd>{detail.reminder.deliveryError ?? "无"}</dd></div>
                        </dl>
                      )}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {pendingDelete === null ? null : (
        <div className="confirmation-layer">
          <div className="confirmation-backdrop" />
          <section
            aria-labelledby="reminder-delete-title"
            aria-modal="true"
            className="reminder-confirmation"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                void cancelDelete();
              } else if (
                event.key === "Tab"
                && event.shiftKey
                && document.activeElement === cancelDeleteButton.current
              ) {
                event.preventDefault();
                confirmDeleteButton.current?.focus();
              } else if (
                event.key === "Tab"
                && !event.shiftKey
                && document.activeElement === confirmDeleteButton.current
              ) {
                event.preventDefault();
                cancelDeleteButton.current?.focus();
              }
            }}
            role="dialog"
          >
            <span>需要确认</span>
            <h2 id="reminder-delete-title">删除提醒</h2>
            <p>确认删除“{pendingDelete.reminder.message}”？此操作会删除该提醒记录。</p>
            <p
              aria-label="删除状态"
              aria-live="polite"
              className="confirmation-status"
              role="status"
            >
              {confirmationError}
            </p>
            <div>
              <button
                className="quiet-button"
                onClick={() => void cancelDelete()}
                ref={cancelDeleteButton}
                type="button"
              >
                取消
              </button>
              <button
                className="danger-button"
                disabled={busyReminderId === pendingDelete.reminder.id}
                onClick={() => void confirmDelete()}
                ref={confirmDeleteButton}
                type="button"
              >
                确认删除
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
