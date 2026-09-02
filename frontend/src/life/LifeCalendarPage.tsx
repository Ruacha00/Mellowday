import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";

import type {
  CalendarEvent,
  CalendarEventDraft,
  CalendarEventService,
} from "../services/calendarEventApi";
import { LatestRequest } from "../services/requestLifecycle";

interface LifeCalendarPageProps {
  service: CalendarEventService;
}

interface EditorDraft {
  title: string;
  startAt: string;
  endAt: string;
  details: string;
}

interface DeleteConfirmation {
  calendarEvent: CalendarEvent;
  confirmation: Awaited<
    ReturnType<CalendarEventService["requestDeleteConfirmation"]>
  >;
}

interface EventDetail {
  eventId: string;
  state: "loading" | "ready" | "error";
  calendarEvent: CalendarEvent | null;
  conflicts: CalendarEvent[];
}

const emptyDraft: EditorDraft = {
  title: "",
  startAt: "",
  endAt: "",
  details: "",
};

function toLocalInputValue(value: string): string {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match === null ? "" : `${match[1]}T${match[2]}`;
}

function formatCalendarDateTime(value: string): string {
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/,
  );
  return match === null
    ? value
    : `${match[1]}年${match[2]}月${match[3]}日 ${match[4]}:${match[5]}`;
}

function isValidDateTime(value: string): boolean {
  return value.length > 0 && !Number.isNaN(new Date(value).getTime());
}

export function LifeCalendarPage({ service }: LifeCalendarPageProps) {
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [conflicts, setConflicts] = useState<Record<string, CalendarEvent[]>>(
    {},
  );
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [draft, setDraft] = useState<EditorDraft>(emptyDraft);
  const [editingEventId, setEditingEventId] = useState<string | null>(null);
  const [busyEventId, setBusyEventId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [confirmationError, setConfirmationError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<DeleteConfirmation | null>(
    null,
  );
  const loadRequest = useRef(new LatestRequest());
  const detailRequest = useRef(new LatestRequest());
  const saveRequest = useRef(new LatestRequest());
  const deleteRequest = useRef(new LatestRequest());
  const mounted = useRef(false);
  const titleInput = useRef<HTMLInputElement>(null);
  const startAtInput = useRef<HTMLInputElement>(null);
  const endAtInput = useRef<HTMLInputElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const confirmDeleteButton = useRef<HTMLButtonElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  const loadCalendarEvents = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    void loadRequest.current
      .run((signal) => service.listCalendarEvents(signal))
      .then((result) => {
        if (!mounted.current || result.status !== "current") {
          return;
        }
        setCalendarEvents(result.value.calendarEvents);
        setConflicts(result.value.conflicts);
        setDetail((current) => {
          if (current === null || current.state !== "ready") {
            return current;
          }
          const latest = result.value.calendarEvents.find(
            (event) => event.id === current.eventId,
          );
          return latest === undefined
            ? null
            : {
                ...current,
                calendarEvent: latest,
                conflicts: result.value.conflicts[latest.id] ?? [],
              };
        });
        setLoadState("ready");
      })
      .catch(() => {
        if (mounted.current) {
          setLoadState("error");
        }
      });
  }, [service]);

  useEffect(() => {
    mounted.current = true;
    loadCalendarEvents(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      detailRequest.current.cancel();
      saveRequest.current.cancel();
      deleteRequest.current.cancel();
    };
  }, [loadCalendarEvents]);

  useEffect(() => {
    if (pendingDelete !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [pendingDelete]);

  const resetEditor = () => {
    setDraft(emptyDraft);
    setEditingEventId(null);
  };

  const editCalendarEvent = (calendarEvent: CalendarEvent) => {
    setDraft({
      title: calendarEvent.title,
      startAt: toLocalInputValue(calendarEvent.startAt),
      endAt: calendarEvent.endAt === null
        ? ""
        : toLocalInputValue(calendarEvent.endAt),
      details: calendarEvent.details ?? "",
    });
    setEditingEventId(calendarEvent.id);
    window.requestAnimationFrame(() => titleInput.current?.focus());
  };

  const saveCalendarEvent = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = draft.title.trim();
    if (title.length === 0) {
      setNotice("请输入事件标题。");
      titleInput.current?.focus();
      return;
    }
    if (!isValidDateTime(draft.startAt)) {
      setNotice("请选择有效的开始时间。");
      startAtInput.current?.focus();
      return;
    }
    if (draft.endAt.length > 0 && !isValidDateTime(draft.endAt)) {
      setNotice("请选择有效的结束时间。");
      endAtInput.current?.focus();
      return;
    }
    if (
      draft.endAt.length > 0
      && new Date(draft.endAt).getTime() <= new Date(draft.startAt).getTime()
    ) {
      setNotice("结束时间必须晚于开始时间。");
      endAtInput.current?.focus();
      return;
    }
    const payload: CalendarEventDraft = {
      title,
      startAt: draft.startAt,
      endAt: draft.endAt || null,
      details: draft.details.trim() || null,
    };
    const eventId = editingEventId;
    setSubmitting(true);
    setNotice("");
    try {
      const result = await saveRequest.current.run((signal) =>
        eventId === null
          ? service.createCalendarEvent(payload, signal)
          : service.updateCalendarEvent(eventId, payload, signal),
      );
      if (!mounted.current || result.status !== "current") {
        return;
      }
      setNotice(eventId === null ? "日历事件已添加。" : "日历事件已保存。");
      resetEditor();
      loadCalendarEvents(false);
    } catch {
      if (mounted.current) {
        setNotice(eventId === null ? "日历事件添加失败。" : "日历事件保存失败。");
      }
    } finally {
      if (mounted.current) {
        setSubmitting(false);
      }
    }
  };

  const inspectCalendarEvent = (calendarEvent: CalendarEvent) => {
    if (detail?.eventId === calendarEvent.id) {
      detailRequest.current.cancel();
      setDetail(null);
      return;
    }
    setDetail({
      eventId: calendarEvent.id,
      state: "loading",
      calendarEvent: null,
      conflicts: [],
    });
    void detailRequest.current
      .run((signal) => service.getCalendarEvent(calendarEvent.id, signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setDetail({
            eventId: calendarEvent.id,
            state: "ready",
            calendarEvent: result.value.calendarEvent,
            conflicts: result.value.conflicts,
          });
        }
      })
      .catch(() => {
        if (mounted.current) {
          setDetail({
            eventId: calendarEvent.id,
            state: "error",
            calendarEvent: null,
            conflicts: [],
          });
        }
      });
  };

  const requestDelete = async (
    calendarEvent: CalendarEvent,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    deleteTrigger.current = event.currentTarget;
    setBusyEventId(calendarEvent.id);
    setNotice("正在准备删除确认…");
    setConfirmationError("");
    try {
      const result = await deleteRequest.current.run((signal) =>
        service.requestDeleteConfirmation(calendarEvent.id, signal),
      );
      if (!mounted.current || result.status !== "current") {
        return;
      }
      setPendingDelete({ calendarEvent, confirmation: result.value });
      setNotice("");
    } catch {
      if (mounted.current) {
        setNotice("无法准备日历事件删除确认。");
      }
    } finally {
      if (mounted.current) {
        setBusyEventId(null);
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
    setBusyEventId(current.calendarEvent.id);
    setConfirmationError("");
    try {
      const result = await deleteRequest.current.run((signal) =>
        service.decideDelete(
          current.calendarEvent.id,
          current.confirmation,
          "reject",
          signal,
        ),
      );
      if (!mounted.current || result.status !== "current") {
        return;
      }
      setPendingDelete(null);
      setNotice("已取消删除日历事件。");
      restoreDeleteFocus();
    } catch {
      if (mounted.current) {
        setConfirmationError("取消删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyEventId(null);
      }
    }
  };

  const confirmDelete = async () => {
    const current = pendingDelete;
    if (current === null) {
      return;
    }
    setBusyEventId(current.calendarEvent.id);
    setConfirmationError("");
    try {
      const result = await deleteRequest.current.run((signal) =>
        service.decideDelete(
          current.calendarEvent.id,
          current.confirmation,
          "accept",
          signal,
        ),
      );
      if (
        !mounted.current
        || result.status !== "current"
      ) {
        return;
      }
      if (!result.value.ok) {
        throw new Error("Calendar Event deletion was rejected");
      }
      setPendingDelete(null);
      setNotice("日历事件已删除。");
      if (editingEventId === current.calendarEvent.id) {
        resetEditor();
      }
      if (detail?.eventId === current.calendarEvent.id) {
        setDetail(null);
      }
      loadCalendarEvents(false);
    } catch {
      if (mounted.current) {
        setConfirmationError("日历事件删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyEventId(null);
      }
    }
  };

  return (
    <div className="calendar-page">
      <section aria-labelledby="calendar-editor-title" className="calendar-editor reminder-editor">
        <div className="calendar-section-heading reminder-section-heading">
          <div>
            <span>时间安排</span>
            <h2 id="calendar-editor-title">
              {editingEventId === null ? "添加日历事件" : "编辑日历事件"}
            </h2>
          </div>
          {editingEventId === null ? null : (
            <button className="quiet-button" onClick={resetEditor} type="button">
              取消编辑
            </button>
          )}
        </div>
        <form className="calendar-form reminder-form" noValidate onSubmit={saveCalendarEvent}>
          <label>
            <span>事件标题</span>
            <input
              autoComplete="off"
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              ref={titleInput}
              type="text"
              value={draft.title}
            />
          </label>
          <div className="calendar-time-fields">
            <label>
              <span>开始时间</span>
              <input
                onChange={(event) => setDraft({ ...draft, startAt: event.target.value })}
                ref={startAtInput}
                type="datetime-local"
                value={draft.startAt}
              />
            </label>
            <label>
              <span>结束时间（可选）</span>
              <input
                onChange={(event) => setDraft({ ...draft, endAt: event.target.value })}
                ref={endAtInput}
                type="datetime-local"
                value={draft.endAt}
              />
            </label>
          </div>
          <label>
            <span>事件详情（可选）</span>
            <textarea
              onChange={(event) => setDraft({ ...draft, details: event.target.value })}
              rows={3}
              value={draft.details}
            />
          </label>
          <button className="primary-button" disabled={submitting} type="submit">
            {submitting
              ? "正在保存…"
              : editingEventId === null
                ? "添加日历事件"
                : "保存日历事件"}
          </button>
        </form>
      </section>

      <p
        aria-label="日历事件状态"
        aria-live="polite"
        className="calendar-notice reminder-notice"
        role="status"
      >
        {notice}
      </p>

      <section aria-labelledby="calendar-list-title" className="calendar-list-section reminder-list-section">
        <div className="calendar-section-heading reminder-section-heading">
          <div>
            <span>生活记录</span>
            <h2 id="calendar-list-title">日历事件列表</h2>
          </div>
          {loadState === "ready" ? <span>{calendarEvents.length} 项</span> : null}
        </div>
        {loadState === "loading" ? (
          <p className="calendar-state reminder-state" role="status">正在加载日历事件…</p>
        ) : loadState === "error" ? (
          <div className="calendar-state reminder-state" role="alert">
            <p>日历事件加载失败。</p>
            <button className="quiet-button" onClick={() => loadCalendarEvents(true)} type="button">
              重试
            </button>
          </div>
        ) : calendarEvents.length === 0 ? (
          <p className="calendar-state reminder-state">还没有日历事件。</p>
        ) : (
          <div className="calendar-list reminder-list">
            {calendarEvents.map((calendarEvent) => {
              const showingDetail = detail?.eventId === calendarEvent.id;
              const eventConflicts = conflicts[calendarEvent.id] ?? [];
              return (
                <article className="calendar-card reminder-card" key={calendarEvent.id}>
                  <div className="calendar-card-heading reminder-card-heading">
                    <h3>{calendarEvent.title}</h3>
                    {eventConflicts.length === 0 ? null : (
                      <span>{eventConflicts.length} 个时间冲突</span>
                    )}
                  </div>
                  <dl className="calendar-timing">
                    <div>
                      <dt>开始</dt>
                      <dd>{formatCalendarDateTime(calendarEvent.startAt)}</dd>
                    </div>
                    <div>
                      <dt>结束</dt>
                      <dd>{calendarEvent.endAt === null
                        ? "未设置"
                        : formatCalendarDateTime(calendarEvent.endAt)}</dd>
                    </div>
                  </dl>
                  <div className="calendar-actions reminder-actions">
                    <button
                      aria-expanded={showingDetail}
                      aria-label={`${showingDetail ? "收起" : "查看"} ${calendarEvent.title}`}
                      disabled={busyEventId === calendarEvent.id}
                      onClick={() => inspectCalendarEvent(calendarEvent)}
                      type="button"
                    >
                      {showingDetail ? "收起详情" : "查看详情"}
                    </button>
                    <button
                      aria-label={`编辑 ${calendarEvent.title}`}
                      disabled={busyEventId === calendarEvent.id}
                      onClick={() => editCalendarEvent(calendarEvent)}
                      type="button"
                    >
                      编辑
                    </button>
                    <button
                      aria-label={`删除 ${calendarEvent.title}`}
                      disabled={busyEventId === calendarEvent.id}
                      onClick={(event) => void requestDelete(calendarEvent, event)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                  {showingDetail ? (
                    <div className="calendar-details reminder-details" aria-live="polite">
                      {detail.state === "loading" ? (
                        <p role="status">正在加载日历事件详情…</p>
                      ) : detail.state === "error" ? (
                        <p role="alert">日历事件详情加载失败。</p>
                      ) : detail.calendarEvent === null ? null : (
                        <>
                          <p>{detail.calendarEvent.details ?? "没有补充详情。"}</p>
                          <div>
                            <strong>时间冲突</strong>
                            {detail.conflicts.length === 0 ? (
                              <p>没有发现时间冲突。</p>
                            ) : (
                              <ul>
                                {detail.conflicts.map((conflict) => (
                                  <li key={conflict.id}>
                                    {conflict.title}，{formatCalendarDateTime(conflict.startAt)}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </>
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
            aria-labelledby="calendar-delete-title"
            aria-modal="true"
            className="calendar-confirmation reminder-confirmation"
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
            <h2 id="calendar-delete-title">删除日历事件</h2>
            <p>
              确认删除“{pendingDelete.calendarEvent.title}”？此操作会删除该日历事件记录。
            </p>
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
                disabled={busyEventId === pendingDelete.calendarEvent.id}
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
