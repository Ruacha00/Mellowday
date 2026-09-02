import { useCallback, useEffect, useRef, useState } from "react";

import { recentConversationTitle } from "../appShell/recentConversations";
import type {
  ConfirmationDecision,
  Conversation,
  ConversationService,
  ConversationSummary,
  PendingConfirmation,
} from "../services/conversationApi";
import { LatestRequest } from "../services/requestLifecycle";

interface ConversationHistoryPageProps {
  onHistoryChanged: () => void;
  service: ConversationService;
}

interface ResetRequest {
  confirmation: PendingConfirmation;
  summary: ConversationSummary;
}

function formatDateTime(value: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value * 1_000));
}

export function ConversationHistoryPage({
  onHistoryChanged,
  service,
}: ConversationHistoryPageProps) {
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [detailState, setDetailState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [resetRequest, setResetRequest] = useState<ResetRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const listRequest = useRef(new LatestRequest());
  const detailRequest = useRef(new LatestRequest());
  const mutationController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const cancelResetButton = useRef<HTMLButtonElement>(null);
  const resetTrigger = useRef<HTMLButtonElement | null>(null);

  const loadConversations = useCallback((showLoading = true) => {
    if (!mounted.current) return;
    if (showLoading) {
      setLoadState("loading");
      setNotice("");
    }
    void listRequest.current.run((signal) => service.listConversations(signal))
      .then((result) => {
        if (!mounted.current || result.status !== "current") return;
        setSummaries(result.value);
        setLoadState("ready");
        setSelectedId((current) => (
          current !== null && result.value.some((item) => item.conversationId === current)
            ? current
            : null
        ));
      })
      .catch(() => {
        if (mounted.current) setLoadState("error");
      });
  }, [service]);

  useEffect(() => {
    mounted.current = true;
    loadConversations();
    return () => {
      mounted.current = false;
      listRequest.current.cancel();
      detailRequest.current.cancel();
      mutationController.current?.abort();
    };
  }, [loadConversations]);

  useEffect(() => {
    if (resetRequest !== null) cancelResetButton.current?.focus();
  }, [resetRequest]);

  const selectConversation = (summary: ConversationSummary) => {
    setSelectedId(summary.conversationId);
    setConversation(null);
    setDetailState("loading");
    setNotice("");
    void detailRequest.current
      .run((signal) => service.loadConversation(summary.conversationId, signal))
      .then((result) => {
        if (!mounted.current || result.status !== "current") return;
        if (result.value === null) {
          setDetailState("error");
          return;
        }
        setConversation(result.value);
        setDetailState("ready");
      })
      .catch(() => {
        if (mounted.current) setDetailState("error");
      });
  };

  const requestReset = async (
    summary: ConversationSummary,
    trigger: HTMLButtonElement,
  ) => {
    if (busy) return;
    resetTrigger.current = trigger;
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusy(true);
    setNotice("正在准备重置确认…");
    try {
      const confirmation = await service.requestResetConfirmation(
        summary.conversationId,
        controller.signal,
      );
      if (!mounted.current || controller.signal.aborted) return;
      setResetRequest({ confirmation, summary });
      setNotice("");
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("无法准备重置确认，请重试。");
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setBusy(false);
      }
    }
  };

  const decideReset = async (decision: ConfirmationDecision) => {
    if (resetRequest === null || busy) return;
    const activeRequest = resetRequest;
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusy(true);
    setNotice(decision === "accept" ? "正在重置对话历史…" : "正在取消重置…");
    try {
      const result = await service.decideReset(
        activeRequest.confirmation,
        decision,
        controller.signal,
      );
      if (!mounted.current || controller.signal.aborted) return;
      setResetRequest(null);
      if (result.decision === "accept") {
        setConversation(null);
        setSelectedId(null);
        setDetailState("idle");
        setNotice(`对话历史已重置，共移除 ${result.removedMessages} 条消息。`);
        loadConversations(false);
        onHistoryChanged();
      } else {
        setNotice("已取消重置。");
      }
      window.requestAnimationFrame(() => resetTrigger.current?.focus());
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("无法应用重置决定，请重新载入后再试。");
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setBusy(false);
      }
    }
  };

  return (
    <section aria-labelledby="history-page-title" className="history-page">
      <header className="settings-page-intro">
        <span>本地保留内容</span>
        <h2 id="history-page-title">对话历史</h2>
        <p>这里管理已存储的对话转录；它不属于记忆，也不是当前对话的工作状态。</p>
      </header>
      <div className="history-layout">
        <section aria-labelledby="history-list-title" className="history-list-section">
          <header className="settings-section-heading">
            <div><span>已存储会话</span><h3 id="history-list-title">会话列表</h3></div>
            <div className="settings-heading-actions">
              <span>{summaries.length}</span>
              <button className="quiet-button" onClick={() => loadConversations()} type="button">刷新</button>
            </div>
          </header>
          {loadState === "loading" ? (
            <p className="settings-state-inline" role="status">正在加载对话历史…</p>
          ) : loadState === "error" ? (
            <div className="settings-state-inline" role="alert">
              <p>对话历史加载失败。</p>
              <button className="quiet-button" onClick={() => loadConversations()} type="button">重试</button>
            </div>
          ) : summaries.length === 0 ? (
            <p className="settings-state-inline">还没有已存储的对话。</p>
          ) : (
            <div className="history-list">
              {summaries.map((summary) => (
                <button
                  aria-pressed={selectedId === summary.conversationId}
                  className="history-list-item"
                  key={summary.conversationId}
                  onClick={() => selectConversation(summary)}
                  type="button"
                >
                  <strong>{recentConversationTitle(summary)}</strong>
                  <span>{summary.messageCount} 条消息 · {formatDateTime(summary.updatedAt)}</span>
                </button>
              ))}
            </div>
          )}
        </section>
        <section aria-label="会话详情" className="history-detail-section">
          {detailState === "loading" ? (
            <p className="settings-state-inline" role="status">正在加载会话内容…</p>
          ) : detailState === "error" ? (
            <p className="settings-state-inline" role="alert">所选会话加载失败，请重新选择。</p>
          ) : conversation === null ? (
            <p className="settings-state-inline">选择一个会话以查看已存储的转录。</p>
          ) : (
            <>
              <header className="settings-section-heading history-detail-heading">
                <div>
                  <span>{conversation.summary.conversationId}</span>
                  <h3 id="history-detail-title">{recentConversationTitle(conversation.summary)}</h3>
                  <p>{conversation.summary.messageCount} 条消息 · {conversation.summary.characterCount} 个字符</p>
                </div>
                <button
                  className="danger-button"
                  disabled={busy}
                  onClick={(event) => void requestReset(conversation.summary, event.currentTarget)}
                  type="button"
                >重置此对话</button>
              </header>
              <ol aria-label="已存储的对话转录" className="history-transcript">
                {conversation.messages.map((message, index) => (
                  <li data-role={message.role} key={`${message.role}-${index}`}>
                    <span>{message.role === "user" ? "用户" : "助手"}</span>
                    <p>{message.content}</p>
                  </li>
                ))}
              </ol>
            </>
          )}
        </section>
      </div>
      <p aria-live="polite" className="settings-notice" role="status">{notice}</p>
      {resetRequest === null ? null : (
        <div className="confirmation-layer" role="presentation">
          <div className="confirmation-backdrop" />
          <section
            aria-labelledby="history-reset-title"
            aria-modal="true"
            className="history-confirmation"
            onKeyDown={(event) => {
              if (event.key === "Escape" && !busy) void decideReset("reject");
            }}
            role="dialog"
          >
            <span>需要明确确认</span>
            <h2 id="history-reset-title">重置这个对话？</h2>
            <p>这会永久删除“{recentConversationTitle(resetRequest.summary)}”中已存储的消息，不会删除记忆或生活记录。</p>
            <div>
              <button disabled={busy} onClick={() => void decideReset("reject")} ref={cancelResetButton} type="button">取消</button>
              <button className="danger-button" disabled={busy} onClick={() => void decideReset("accept")} type="button">确认重置</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
