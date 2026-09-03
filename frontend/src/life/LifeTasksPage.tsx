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
  Task,
  TaskDraft,
  TaskService,
} from "../services/taskApi";

interface LifeTasksPageProps {
  service: TaskService;
}

interface EditorDraft {
  title: string;
  details: string;
  deadline: string;
}

interface DeleteConfirmation {
  task: Task;
  confirmation: Awaited<ReturnType<TaskService["requestDeleteConfirmation"]>>;
}

const emptyDraft: EditorDraft = {
  title: "",
  details: "",
  deadline: "",
};

export function LifeTasksPage({ service }: LifeTasksPageProps) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [draft, setDraft] = useState<EditorDraft>(emptyDraft);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [confirmationError, setConfirmationError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<DeleteConfirmation | null>(
    null,
  );
  const loadRequest = useRef(new LatestRequest());
  const mounted = useRef(false);
  const titleInput = useRef<HTMLInputElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const confirmDeleteButton = useRef<HTMLButtonElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  const loadTasks = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    void loadRequest.current
      .run((signal) => service.listTasks(signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setTasks(result.value);
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
    loadTasks(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
    };
  }, [loadTasks]);

  useEffect(() => {
    if (pendingDelete !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [pendingDelete]);

  const resetEditor = () => {
    setDraft(emptyDraft);
    setEditingTaskId(null);
  };

  const editTask = (task: Task) => {
    setDraft({
      title: task.title,
      details: task.details ?? "",
      deadline: task.deadline ?? "",
    });
    setEditingTaskId(task.id);
    window.requestAnimationFrame(() => titleInput.current?.focus());
  };

  const saveTask = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = draft.title.trim();
    if (title.length === 0) {
      setNotice("请输入任务标题。");
      titleInput.current?.focus();
      return;
    }
    const payload: TaskDraft = {
      title,
      details: draft.details.trim() || null,
      deadline: draft.deadline || null,
    };
    setSubmitting(true);
    setNotice("");
    try {
      if (editingTaskId === null) {
        await service.createTask(payload);
        if (!mounted.current) {
          return;
        }
        setNotice("任务已添加。");
      } else {
        await service.updateTask(editingTaskId, payload);
        if (!mounted.current) {
          return;
        }
        setNotice("任务已保存。");
      }
      resetEditor();
      loadTasks(false);
    } catch {
      if (mounted.current) {
        setNotice(editingTaskId === null ? "任务添加失败。" : "任务保存失败。");
      }
    } finally {
      if (mounted.current) {
        setSubmitting(false);
      }
    }
  };

  const changeCompletion = async (task: Task) => {
    setBusyTaskId(task.id);
    setNotice("");
    try {
      await service.setCompleted(task.id, !task.completed);
      if (!mounted.current) {
        return;
      }
      setNotice(task.completed ? "任务已重新打开。" : "任务已完成。");
      loadTasks(false);
    } catch {
      if (mounted.current) {
        setNotice("任务状态更新失败。");
      }
    } finally {
      if (mounted.current) {
        setBusyTaskId(null);
      }
    }
  };

  const requestDelete = async (
    task: Task,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    deleteTrigger.current = event.currentTarget;
    setBusyTaskId(task.id);
    setNotice("正在准备删除确认…");
    setConfirmationError("");
    try {
      const confirmation = await service.requestDeleteConfirmation(task.id);
      if (!mounted.current) {
        return;
      }
      setPendingDelete({ task, confirmation });
      setNotice("");
    } catch {
      if (mounted.current) {
        setNotice("无法准备任务删除确认。");
      }
    } finally {
      if (mounted.current) {
        setBusyTaskId(null);
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
    setBusyTaskId(current.task.id);
    setConfirmationError("");
    try {
      await service.decideDelete(
        current.task.id,
        current.confirmation,
        "reject",
      );
      if (!mounted.current) {
        return;
      }
      setPendingDelete(null);
      setNotice("已取消删除任务。");
      restoreDeleteFocus();
    } catch {
      if (mounted.current) {
        setConfirmationError("取消删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyTaskId(null);
      }
    }
  };

  const confirmDelete = async () => {
    if (pendingDelete === null) {
      return;
    }
    const current = pendingDelete;
    setBusyTaskId(current.task.id);
    setConfirmationError("");
    try {
      const result = await service.decideDelete(
        current.task.id,
        current.confirmation,
        "accept",
      );
      if (!result.ok) {
        throw new Error("Task deletion was rejected");
      }
      if (!mounted.current) {
        return;
      }
      setPendingDelete(null);
      setNotice("任务已删除。");
      if (editingTaskId === current.task.id) {
        resetEditor();
      }
      loadTasks(false);
    } catch {
      if (mounted.current) {
        setConfirmationError("任务删除失败，请重试。");
      }
    } finally {
      if (mounted.current) {
        setBusyTaskId(null);
      }
    }
  };

  return (
    <div className="tasks-page">
      <section aria-labelledby="task-editor-title" className="task-editor">
        <div className="task-section-heading">
          <div>
            <span>任务编辑</span>
            <h2 id="task-editor-title">
              {editingTaskId === null ? "添加任务" : "编辑任务"}
            </h2>
          </div>
          {editingTaskId === null ? null : (
            <button className="quiet-button" onClick={resetEditor} type="button">
              取消编辑
            </button>
          )}
        </div>
        <form className="task-form" noValidate onSubmit={saveTask}>
          <label>
            <span>任务标题</span>
            <input
              autoComplete="off"
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              ref={titleInput}
              type="text"
              value={draft.title}
            />
          </label>
          <label>
            <span>任务详情</span>
            <textarea
              onChange={(event) => setDraft({ ...draft, details: event.target.value })}
              rows={3}
              value={draft.details}
            />
          </label>
          <label>
            <span>截止日期</span>
            <input
              onChange={(event) => setDraft({ ...draft, deadline: event.target.value })}
              type="date"
              value={draft.deadline}
            />
          </label>
          <button className="primary-button" disabled={submitting} type="submit">
            {submitting
              ? "正在保存…"
              : editingTaskId === null
                ? "添加任务"
                : "保存任务"}
          </button>
        </form>
      </section>

      <p aria-label="任务状态" aria-live="polite" className="task-notice" role="status">
        {notice}
      </p>

      <section aria-labelledby="task-list-title" className="task-list-section">
        <div className="task-section-heading">
          <div>
            <span>生活记录</span>
            <h2 id="task-list-title">任务列表</h2>
          </div>
          {loadState === "ready" ? <span>{tasks.length} 项</span> : null}
        </div>
        {loadState === "loading" ? (
          <p className="task-state" role="status">正在加载任务…</p>
        ) : loadState === "error" ? (
          <div className="task-state" role="alert">
            <p>任务加载失败。</p>
            <button className="quiet-button" onClick={() => loadTasks(true)} type="button">
              重试
            </button>
          </div>
        ) : tasks.length === 0 ? (
          <p className="task-state">还没有任务。</p>
        ) : (
          <div className="task-list">
            {tasks.map((task) => (
              <article className="task-card" data-completed={task.completed} key={task.id}>
                <div className="task-card-heading">
                  <h3>{task.title}</h3>
                  <span>{task.completed ? "已完成" : "待完成"}</span>
                </div>
                <p>{task.details ?? "无详情"}</p>
                <p className="task-deadline">
                  {task.deadline === null ? "无截止日期" : `截止 ${task.deadline}`}
                </p>
                <div className="task-actions">
                  <button
                    aria-label={`${task.completed ? "重新打开" : "完成"} ${task.title}`}
                    disabled={busyTaskId === task.id}
                    onClick={() => void changeCompletion(task)}
                    type="button"
                  >
                    {task.completed ? "重新打开" : "完成"}
                  </button>
                  <button
                    aria-label={`编辑 ${task.title}`}
                    disabled={busyTaskId === task.id}
                    onClick={() => editTask(task)}
                    type="button"
                  >
                    编辑
                  </button>
                  <button
                    aria-label={`删除 ${task.title}`}
                    disabled={busyTaskId === task.id}
                    onClick={(event) => void requestDelete(task, event)}
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

      {pendingDelete === null ? null : (
        <div className="confirmation-layer">
          <div className="confirmation-backdrop" />
          <section
            aria-labelledby="task-delete-title"
            aria-modal="true"
            className="task-confirmation"
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
            <h2 id="task-delete-title">删除任务</h2>
            <p>确认删除“{pendingDelete.task.title}”？此操作会删除该生活记录。</p>
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
                disabled={busyTaskId === pendingDelete.task.id}
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
