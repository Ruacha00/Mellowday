import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";

import { LatestRequest } from "../services/requestLifecycle";
import type { Note, NoteDraft, NoteService } from "../services/noteApi";

interface LifeNotesPageProps {
  service: NoteService;
}

interface EditorDraft {
  title: string;
  content: string;
}

interface DeleteConfirmation {
  note: Note;
  confirmation: Awaited<ReturnType<NoteService["requestDeleteConfirmation"]>>;
}

const emptyDraft: EditorDraft = {
  title: "",
  content: "",
};

function noteLabel(note: Note): string {
  return note.title ?? "无标题笔记";
}

export function LifeNotesPage({ service }: LifeNotesPageProps) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [draft, setDraft] = useState<EditorDraft>(emptyDraft);
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [busyNoteId, setBusyNoteId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<{
    noteId: string;
    state: "loading" | "ready" | "error";
    note: Note | null;
  } | null>(null);
  const [confirmationError, setConfirmationError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<DeleteConfirmation | null>(
    null,
  );
  const loadRequest = useRef(new LatestRequest());
  const detailRequest = useRef(new LatestRequest());
  const mutationController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const contentInput = useRef<HTMLTextAreaElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const confirmDeleteButton = useRef<HTMLButtonElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  const loadNotes = useCallback((search: string, showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    void loadRequest.current
      .run((signal) => service.listNotes(search, signal))
      .then((result) => {
        if (!mounted.current || result.status !== "current") {
          return;
        }
        setNotes(result.value);
        setDetail((current) => {
          if (current === null || current.state !== "ready") {
            return current;
          }
          const latest = result.value.find((note) => note.id === current.noteId);
          return latest === undefined ? null : { ...current, note: latest };
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
    loadNotes("", true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      detailRequest.current.cancel();
      mutationController.current?.abort();
    };
  }, [loadNotes]);

  useEffect(() => {
    if (pendingDelete !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [pendingDelete]);

  const resetEditor = () => {
    setDraft(emptyDraft);
    setEditingNoteId(null);
  };

  const runSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const search = query.trim();
    setActiveQuery(search);
    loadNotes(search, true);
  };

  const editNote = (note: Note) => {
    setDraft({ title: note.title ?? "", content: note.content });
    setEditingNoteId(note.id);
    window.requestAnimationFrame(() => contentInput.current?.focus());
  };

  const saveNote = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const content = draft.content.trim();
    if (content.length === 0) {
      setNotice("请输入笔记内容。");
      contentInput.current?.focus();
      return;
    }
    const payload: NoteDraft = {
      title: draft.title.trim() || null,
      content,
    };
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setSubmitting(true);
    setNotice("");
    try {
      const saved = editingNoteId === null
        ? await service.createNote(payload, controller.signal)
        : await service.updateNote(editingNoteId, payload, controller.signal);
      if (!mounted.current || controller.signal.aborted) {
        return;
      }
      setNotice(editingNoteId === null ? "笔记已添加。" : "笔记已保存。");
      setDetail((current) => current?.noteId === saved.id
        ? { noteId: saved.id, state: "ready", note: saved }
        : current);
      resetEditor();
      loadNotes(activeQuery, false);
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice(editingNoteId === null ? "笔记添加失败。" : "笔记保存失败。");
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setSubmitting(false);
      }
    }
  };

  const inspectNote = (note: Note) => {
    setDetail({ noteId: note.id, state: "loading", note: null });
    void detailRequest.current
      .run((signal) => service.getNote(note.id, signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setDetail({ noteId: note.id, state: "ready", note: result.value });
        }
      })
      .catch(() => {
        if (mounted.current) {
          setDetail({ noteId: note.id, state: "error", note: null });
        }
      });
  };

  const requestDelete = async (
    note: Note,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    deleteTrigger.current = event.currentTarget;
    setBusyNoteId(note.id);
    setNotice("正在准备删除确认…");
    setConfirmationError("");
    try {
      const confirmation = await service.requestDeleteConfirmation(note.id);
      if (!mounted.current) {
        return;
      }
      setPendingDelete({ note, confirmation });
      setNotice("");
    } catch {
      if (mounted.current) {
        setNotice("无法准备笔记删除确认。");
      }
    } finally {
      if (mounted.current) {
        setBusyNoteId(null);
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
    setBusyNoteId(current.note.id);
    setConfirmationError("");
    try {
      await service.decideDelete(
        current.note.id,
        current.confirmation,
        "reject",
      );
      if (!mounted.current) {
        return;
      }
      setPendingDelete(null);
      setNotice("已取消删除笔记。");
      restoreDeleteFocus();
    } catch {
      if (mounted.current) {
        setConfirmationError("取消删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyNoteId(null);
      }
    }
  };

  const confirmDelete = async () => {
    const current = pendingDelete;
    if (current === null) {
      return;
    }
    setBusyNoteId(current.note.id);
    setConfirmationError("");
    try {
      const result = await service.decideDelete(
        current.note.id,
        current.confirmation,
        "accept",
      );
      if (!result.ok) {
        throw new Error("Note deletion was rejected");
      }
      if (!mounted.current) {
        return;
      }
      setPendingDelete(null);
      setNotice("笔记已删除。");
      if (editingNoteId === current.note.id) {
        resetEditor();
      }
      if (detail?.noteId === current.note.id) {
        setDetail(null);
      }
      loadNotes(activeQuery, false);
    } catch {
      if (mounted.current) {
        setConfirmationError("笔记删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyNoteId(null);
      }
    }
  };

  return (
    <div className="notes-page">
      <section aria-labelledby="note-editor-title" className="note-editor">
        <div className="note-section-heading">
          <div>
            <span>生活记录</span>
            <h2 id="note-editor-title">
              {editingNoteId === null ? "添加笔记" : "编辑笔记"}
            </h2>
          </div>
          {editingNoteId === null ? null : (
            <button className="quiet-button" onClick={resetEditor} type="button">
              取消编辑
            </button>
          )}
        </div>
        <p className="note-boundary">
          笔记用于保存自由文本，作为生活记录独立管理。
        </p>
        <form className="note-form" noValidate onSubmit={saveNote}>
          <label>
            <span>笔记标题（可选）</span>
            <input
              autoComplete="off"
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              type="text"
              value={draft.title}
            />
          </label>
          <label>
            <span>笔记内容</span>
            <textarea
              onChange={(event) => setDraft({ ...draft, content: event.target.value })}
              ref={contentInput}
              rows={8}
              value={draft.content}
            />
          </label>
          <button className="primary-button" disabled={submitting} type="submit">
            {submitting
              ? "正在保存…"
              : editingNoteId === null
                ? "添加笔记"
                : "保存笔记"}
          </button>
        </form>
      </section>

      <p aria-label="笔记状态" aria-live="polite" className="note-notice" role="status">
        {notice}
      </p>

      <section aria-labelledby="note-list-title" className="note-list-section">
        <div className="note-section-heading">
          <div>
            <span>生活记录</span>
            <h2 id="note-list-title">笔记列表</h2>
          </div>
          {loadState === "ready" ? <span>{notes.length} 条</span> : null}
        </div>
        <form className="note-search" role="search" onSubmit={runSearch}>
          <label>
            <span>搜索笔记</span>
            <input
              onChange={(event) => setQuery(event.target.value)}
              type="search"
              value={query}
            />
          </label>
          <button type="submit">搜索</button>
        </form>
        {loadState === "loading" ? (
          <p className="note-state" role="status">正在加载笔记…</p>
        ) : loadState === "error" ? (
          <div className="note-state" role="alert">
            <p>笔记加载失败。</p>
            <button
              className="quiet-button"
              onClick={() => loadNotes(activeQuery, true)}
              type="button"
            >
              重试
            </button>
          </div>
        ) : notes.length === 0 ? (
          <p className="note-state">
            {activeQuery.length === 0 ? "还没有笔记。" : "没有匹配的笔记。"}
          </p>
        ) : (
          <div className="note-list">
            {notes.map((note) => (
              <article className="note-card" key={note.id}>
                <div className="note-card-heading">
                  <h3>{noteLabel(note)}</h3>
                </div>
                <p className="note-preview">{note.content}</p>
                <div className="note-actions">
                  <button
                    aria-label={`查看 ${noteLabel(note)}`}
                    disabled={busyNoteId === note.id}
                    onClick={() => inspectNote(note)}
                    type="button"
                  >
                    查看
                  </button>
                  <button
                    aria-label={`编辑 ${noteLabel(note)}`}
                    disabled={busyNoteId === note.id}
                    onClick={() => editNote(note)}
                    type="button"
                  >
                    编辑
                  </button>
                  <button
                    aria-label={`删除 ${noteLabel(note)}`}
                    disabled={busyNoteId === note.id}
                    onClick={(event) => void requestDelete(note, event)}
                    type="button"
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {detail === null ? null : (
        <section aria-labelledby="note-detail-title" className="note-details">
          <div className="note-section-heading">
            <div>
              <span>笔记详情</span>
              <h2 id="note-detail-title">
                {detail.note === null ? "正在读取" : noteLabel(detail.note)}
              </h2>
            </div>
            <button
              aria-label="关闭笔记详情"
              className="quiet-button"
              onClick={() => {
                detailRequest.current.cancel();
                setDetail(null);
              }}
              type="button"
            >
              关闭
            </button>
          </div>
          {detail.state === "loading" ? (
            <p role="status">正在加载笔记详情…</p>
          ) : detail.state === "error" ? (
            <div role="alert">
              <p>笔记详情加载失败。</p>
              <button
                className="quiet-button"
                onClick={() => {
                  const note = notes.find((item) => item.id === detail.noteId);
                  if (note !== undefined) {
                    inspectNote(note);
                  }
                }}
                type="button"
              >
                重试
              </button>
            </div>
          ) : (
            <pre className="note-content">{detail.note?.content}</pre>
          )}
        </section>
      )}

      {pendingDelete === null ? null : (
        <div className="confirmation-layer">
          <div className="confirmation-backdrop" />
          <section
            aria-labelledby="note-delete-title"
            aria-modal="true"
            className="note-confirmation"
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
            <h2 id="note-delete-title">删除笔记</h2>
            <p>
              确认删除“{noteLabel(pendingDelete.note)}”？此操作会删除该生活记录。
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
                disabled={busyNoteId === pendingDelete.note.id}
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
