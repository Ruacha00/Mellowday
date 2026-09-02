import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import type { PendingConfirmation } from "../services/conversationApi";
import type {
  Memory,
  MemoryDraft,
  MemoryKind,
  MemoryService,
} from "../services/memoryApi";
import { LatestRequest } from "../services/requestLifecycle";

export type MemoryLoadState = "loading" | "ready" | "error";

export interface MemorySearchSnapshot {
  appliedQuery: string;
  loadState: MemoryLoadState;
  memories: Memory[];
}

interface MemoryManagementPageProps {
  service: MemoryService;
}

interface PendingDelete {
  memory: Memory;
  confirmation: PendingConfirmation;
}

const initialSearchSnapshot: MemorySearchSnapshot = {
  appliedQuery: "",
  loadState: "loading",
  memories: [],
};

const kindLabels: Record<MemoryKind, string> = {
  preference: "偏好",
  fact: "事实",
  important: "重要事项",
};

/** Owns cancellable, route-scoped Memory searches independently of rendering. */
export class MemorySearchCoordinator {
  private readonly request = new LatestRequest();
  private disposed = false;
  private snapshot = initialSearchSnapshot;

  constructor(
    private readonly service: Pick<MemoryService, "listMemories">,
    private readonly publish: (snapshot: MemorySearchSnapshot) => void,
  ) {}

  async search(query: string, showLoading = true): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    const normalizedQuery = query.trim();
    this.update({
      appliedQuery: normalizedQuery,
      ...(showLoading ? { loadState: "loading" as const } : {}),
    });
    try {
      const result = await this.request.run((signal) =>
        this.service.listMemories(normalizedQuery, signal),
      );
      if (result.status !== "current" || this.disposed) {
        return false;
      }
      this.update({ loadState: "ready", memories: result.value });
      return true;
    } catch {
      if (!this.disposed) {
        this.update({ loadState: "error" });
      }
      return false;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.request.cancel();
  }

  private update(patch: Partial<MemorySearchSnapshot>): void {
    if (this.disposed) {
      return;
    }
    this.snapshot = { ...this.snapshot, ...patch };
    this.publish(this.snapshot);
  }
}

export function MemoryManagementPage({ service }: MemoryManagementPageProps) {
  const [snapshot, setSnapshot] = useState(initialSearchSnapshot);
  const [query, setQuery] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Memory | null>(null);
  const [draft, setDraft] = useState<MemoryDraft>({
    content: "",
    kind: "fact",
  });
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [busyMemoryId, setBusyMemoryId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [confirmationError, setConfirmationError] = useState("");
  const coordinator = useRef<MemorySearchCoordinator | null>(null);
  const mounted = useRef(false);
  const mutationController = useRef<AbortController | null>(null);
  const contentInput = useRef<HTMLTextAreaElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const confirmDeleteButton = useRef<HTMLButtonElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    mounted.current = true;
    setSnapshot(initialSearchSnapshot);
    const nextCoordinator = new MemorySearchCoordinator(service, setSnapshot);
    coordinator.current = nextCoordinator;
    void nextCoordinator.search("");
    return () => {
      mounted.current = false;
      nextCoordinator.dispose();
      mutationController.current?.abort();
      if (coordinator.current === nextCoordinator) {
        coordinator.current = null;
      }
    };
  }, [service]);

  useEffect(() => {
    if (pendingDelete !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [pendingDelete]);

  useEffect(() => {
    if (detailId !== null && !snapshot.memories.some((memory) => memory.id === detailId)) {
      setDetailId(null);
    }
    if (editing !== null && !snapshot.memories.some((memory) => memory.id === editing.id)) {
      setEditing(null);
    }
  }, [detailId, editing, snapshot.memories]);

  const runSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setNotice("");
    void coordinator.current?.search(query);
  };

  const beginEdit = (memory: Memory) => {
    setEditing(memory);
    setDraft({ content: memory.content, kind: memory.kind });
    setNotice("");
    window.requestAnimationFrame(() => contentInput.current?.focus());
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft({ content: "", kind: "fact" });
  };

  const saveMemory = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editing === null || busyMemoryId !== null) {
      return;
    }
    const content = draft.content.trim();
    if (content.length === 0) {
      setNotice("记忆内容不能为空。");
      contentInput.current?.focus();
      return;
    }
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusyMemoryId(editing.id);
    setNotice("");
    try {
      await service.updateMemory(
        editing.id,
        { content, kind: draft.kind },
        controller.signal,
      );
      if (!mounted.current || controller.signal.aborted) {
        return;
      }
      cancelEdit();
      setNotice("记忆已保存。");
      await coordinator.current?.search(snapshot.appliedQuery, false);
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("记忆保存失败，请重试。");
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setBusyMemoryId(null);
      }
    }
  };

  const requestDelete = async (
    memory: Memory,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    if (busyMemoryId !== null) {
      return;
    }
    deleteTrigger.current = event.currentTarget;
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusyMemoryId(memory.id);
    setNotice("正在准备删除确认…");
    setConfirmationError("");
    try {
      const confirmation = await service.requestDeleteConfirmation(
        memory.id,
        controller.signal,
      );
      if (!mounted.current || controller.signal.aborted) {
        return;
      }
      setPendingDelete({ memory, confirmation });
      setNotice("");
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("无法准备记忆删除确认，请重试。");
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setBusyMemoryId(null);
      }
    }
  };

  const restoreDeleteFocus = () => {
    window.requestAnimationFrame(() => deleteTrigger.current?.focus());
  };

  const decideDelete = async (decision: "accept" | "reject") => {
    const current = pendingDelete;
    if (current === null || busyMemoryId !== null) {
      return;
    }
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusyMemoryId(current.memory.id);
    setConfirmationError("");
    try {
      const result = await service.decideDelete(
        current.memory.id,
        current.confirmation,
        decision,
        controller.signal,
      );
      if (!mounted.current || controller.signal.aborted) {
        return;
      }
      if (decision === "accept" && !result.ok) {
        throw new Error("Memory deletion was rejected");
      }
      setPendingDelete(null);
      if (decision === "reject") {
        setNotice("已取消删除记忆。");
        restoreDeleteFocus();
        return;
      }
      if (editing?.id === current.memory.id) {
        cancelEdit();
      }
      if (detailId === current.memory.id) {
        setDetailId(null);
      }
      setNotice("记忆已删除。");
      await coordinator.current?.search(snapshot.appliedQuery, false);
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setConfirmationError(
          decision === "accept"
            ? "记忆删除失败，请重试。"
            : "取消删除失败，请重试。",
        );
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setBusyMemoryId(null);
      }
    }
  };

  const handleConfirmationKeys = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      void decideDelete("reject");
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
  };

  return (
    <div className="memory-page">
      <section aria-labelledby="memory-search-title" className="memory-search-panel">
        <div className="memory-section-heading">
          <div>
            <span>长期保留的信息</span>
            <h2 id="memory-search-title">查找记忆</h2>
          </div>
          {snapshot.loadState === "ready" ? <span>{snapshot.memories.length} 项</span> : null}
        </div>
        <p>这里只管理记忆；任务、提醒、日历事件、笔记和对话历史保留在各自的产品区域。</p>
        <form className="memory-search-form" role="search" onSubmit={runSearch}>
          <label htmlFor="memory-search">搜索记忆</label>
          <div>
            <input
              autoComplete="off"
              id="memory-search"
              onChange={(event) => setQuery(event.target.value)}
              type="search"
              value={query}
            />
            <button type="submit">搜索</button>
          </div>
        </form>
      </section>

      <p aria-label="记忆状态" aria-live="polite" className="memory-notice" role="status">
        {notice}
      </p>

      {editing === null ? null : (
        <section aria-labelledby="memory-editor-title" className="memory-editor">
          <div className="memory-section-heading">
            <h2 id="memory-editor-title">编辑记忆</h2>
            <button className="quiet-button" onClick={cancelEdit} type="button">
              取消编辑
            </button>
          </div>
          <form noValidate onSubmit={saveMemory}>
            <label>
              <span>记忆内容</span>
              <textarea
                onChange={(event) => setDraft({ ...draft, content: event.target.value })}
                ref={contentInput}
                rows={4}
                value={draft.content}
              />
            </label>
            <label>
              <span>记忆类型</span>
              <select
                onChange={(event) => setDraft({
                  ...draft,
                  kind: event.target.value as MemoryKind,
                })}
                value={draft.kind}
              >
                <option value="preference">偏好</option>
                <option value="fact">事实</option>
                <option value="important">重要事项</option>
              </select>
            </label>
            <button
              className="primary-button"
              disabled={busyMemoryId === editing.id}
              type="submit"
            >
              {busyMemoryId === editing.id ? "正在保存…" : "保存记忆"}
            </button>
          </form>
        </section>
      )}

      <section aria-labelledby="memory-list-title" className="memory-list-section">
        <div className="memory-section-heading">
          <div>
            <span>{snapshot.appliedQuery ? "搜索结果" : "全部记忆"}</span>
            <h2 id="memory-list-title">记忆列表</h2>
          </div>
        </div>
        {snapshot.loadState === "loading" ? (
          <p className="memory-state" role="status">正在加载记忆…</p>
        ) : snapshot.loadState === "error" ? (
          <div className="memory-state" role="alert">
            <p>记忆加载失败。</p>
            <button
              className="quiet-button"
              onClick={() => void coordinator.current?.search(snapshot.appliedQuery)}
              type="button"
            >
              重试
            </button>
          </div>
        ) : snapshot.memories.length === 0 ? (
          <p className="memory-state">
            {snapshot.appliedQuery ? "没有匹配的记忆。" : "还没有记忆。"}
          </p>
        ) : (
          <div className="memory-list">
            {snapshot.memories.map((memory) => {
              const showingDetail = detailId === memory.id;
              return (
                <article className="memory-card" key={memory.id}>
                  <div className="memory-card-heading">
                    <h3>{memory.content}</h3>
                    <span>{kindLabels[memory.kind]}</span>
                  </div>
                  <p className="memory-card-meta">更新于 {formatTimestamp(memory.updatedAt)}</p>
                  <div className="memory-actions">
                    <button
                      aria-expanded={showingDetail}
                      aria-label={`${showingDetail ? "收起" : "查看"} ${memory.content}`}
                      disabled={busyMemoryId === memory.id}
                      onClick={() => setDetailId(showingDetail ? null : memory.id)}
                      type="button"
                    >
                      {showingDetail ? "收起详情" : "查看详情"}
                    </button>
                    <button
                      aria-label={`编辑 ${memory.content}`}
                      disabled={busyMemoryId === memory.id}
                      onClick={() => beginEdit(memory)}
                      type="button"
                    >
                      编辑
                    </button>
                    <button
                      aria-label={`删除 ${memory.content}`}
                      disabled={busyMemoryId === memory.id}
                      onClick={(event) => void requestDelete(memory, event)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                  {showingDetail ? (
                    <div className="memory-details">
                      <dl>
                        <div><dt>类型</dt><dd>{kindLabels[memory.kind]}</dd></div>
                        <div><dt>保存方式</dt><dd>{provenanceLabel(memory)}</dd></div>
                        <div><dt>创建时间</dt><dd>{formatTimestamp(memory.createdAt)}</dd></div>
                        <div><dt>更新时间</dt><dd>{formatTimestamp(memory.updatedAt)}</dd></div>
                      </dl>
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
            aria-labelledby="memory-delete-title"
            aria-modal="true"
            className="memory-confirmation"
            onKeyDown={handleConfirmationKeys}
            role="dialog"
          >
            <span>需要确认</span>
            <h2 id="memory-delete-title">删除记忆</h2>
            <p>确认删除“{pendingDelete.memory.content}”？删除后，这条信息不会再用于之后的对话。</p>
            <p aria-label="删除状态" aria-live="polite" className="confirmation-status" role="status">
              {confirmationError}
            </p>
            <div>
              <button
                className="quiet-button"
                disabled={busyMemoryId === pendingDelete.memory.id}
                onClick={() => void decideDelete("reject")}
                ref={cancelDeleteButton}
                type="button"
              >
                取消
              </button>
              <button
                className="danger-button"
                disabled={busyMemoryId === pendingDelete.memory.id}
                onClick={() => void decideDelete("accept")}
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

function provenanceLabel(memory: Memory): string {
  return memory.provenance === "explicit" ? "由你明确保存" : "从稳定信息中保存";
}

function formatTimestamp(value: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value * 1_000));
}
