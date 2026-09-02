import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  browserApplicationServices,
  type ApplicationServices,
} from "./services/applicationServices";
import type {
  ChatMessage,
  Conversation,
} from "./services/conversationApi";
import type { LiveConversationEvent } from "./services/liveEvents";
import { LatestRequest } from "./services/requestLifecycle";

const MigrationDetails = lazy(() => import("./MigrationDetails"));
const activeConversationId = "main";

interface AppProps {
  services?: ApplicationServices;
}

export function App({ services = browserApplicationServices }: AppProps) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [latestLiveEvent, setLatestLiveEvent] =
    useState<LiveConversationEvent | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const historyRequest = useRef(new LatestRequest());

  const refreshConversation = useCallback((showLoadingState: boolean) => {
    if (showLoadingState) {
      setLoadState("loading");
    }
    void historyRequest.current
      .run(async (signal) => {
        const summaries = await services.conversation.listConversations(signal);
        const activeConversation = summaries.some(
          (summary) => summary.conversationId === activeConversationId,
        );
        return activeConversation
          ? services.conversation.loadConversation(
              activeConversationId,
              signal,
            )
          : null;
      })
      .then((result) => {
        if (result.status === "current") {
          setConversation(result.value);
          setLoadState("ready");
        }
      })
      .catch(() => {
        setLoadState("error");
      });
  }, [services.conversation]);

  useEffect(() => {
    refreshConversation(true);
    return () => {
      historyRequest.current.cancel();
    };
  }, [refreshConversation]);

  useEffect(() => {
    const unsubscribe = services.liveEvents.subscribe((event) => {
      setLatestLiveEvent(event);
      refreshConversation(false);
    });
    services.liveEvents.start();
    return unsubscribe;
  }, [refreshConversation, services.liveEvents]);

  const messages: ChatMessage[] = conversation?.messages ?? [];

  return (
    <main className="migration-shell">
      <section aria-labelledby="migration-title" className="migration-card">
        <p className="eyebrow">Temporary migration entry</p>
        <h1 id="migration-title">Mellowday React migration</h1>
        <p>
          The production React and TypeScript toolchain is connected. The
          existing Conversation Surface remains available at the main entry.
        </p>
        <section aria-labelledby="conversation-tracer-title">
          <div className="tracer-heading">
            <h2 id="conversation-tracer-title">会话追踪</h2>
            <span className="tracer-state">
              {loadState === "loading" && "正在加载已存会话…"}
              {loadState === "ready" && "已加载存储会话。"}
              {loadState === "error" && "无法读取存储会话。"}
            </span>
          </div>
          <p aria-atomic="true" aria-live="polite" className="visually-hidden">
            {latestLiveEvent === null
              ? ""
              : `${liveSourceLabel(latestLiveEvent.kind)}：${latestLiveEvent.message.content}`}
          </p>
          <ol aria-label="会话记录" className="transcript">
            {messages.length === 0 && loadState !== "loading" ? (
              <li className="empty-transcript">还没有已存消息。</li>
            ) : null}
            {messages.map((message, index) => (
              <TranscriptMessage
                key={`stored-${index}`}
                message={message}
              />
            ))}
          </ol>
        </section>
        <Suspense fallback={<p>Loading migration details…</p>}>
          <MigrationDetails />
        </Suspense>
      </section>
    </main>
  );
}

function TranscriptMessage({
  message,
}: {
  message: ChatMessage;
}) {
  return (
    <li className={`tracer-message tracer-message-${message.role}`}>
      <span className="tracer-role">
        {message.role === "user" ? "用户" : "助手"}
      </span>
      <p>{message.content}</p>
    </li>
  );
}

function liveSourceLabel(kind: LiveConversationEvent["kind"]): string {
  return kind === "reminder" ? "提醒" : "主动聊天";
}
