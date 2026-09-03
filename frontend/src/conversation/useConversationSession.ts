import { useEffect, useRef, useState } from "react";

import type {
  ConfirmationDecision,
  ConversationService,
  PendingConfirmation,
  Turn,
} from "../services/conversationApi";
import type {
  ConversationConfirmationPhase,
  ConversationConfirmationView,
  ConversationEntry,
} from "./ConversationSurface";

interface ConversationSessionState {
  confirmations: ConversationConfirmationView[];
  draft: string;
  operation?: ConversationEntry;
  sending: boolean;
}

interface ConversationSessionOptions {
  conversationId: string;
  onRefresh: (conversationId: string) => void;
  onTurn: (turn: Turn) => void;
  service: ConversationService;
}

export interface ConversationSession {
  confirmations: ConversationConfirmationView[];
  decideConfirmation(
    confirmationId: string,
    decision: ConfirmationDecision,
  ): void;
  draft: string;
  operation?: ConversationEntry;
  send(): void;
  sending: boolean;
  setDraft(value: string): void;
}

export function useConversationSession({
  conversationId,
  onRefresh,
  onTurn,
  service,
}: ConversationSessionOptions): ConversationSession {
  const [sessions, setSessions] = useState<
    Record<string, ConversationSessionState | undefined>
  >({});
  const sendingConversationIds = useRef(new Set<string>());
  const decidingConfirmationIds = useRef(new Set<string>());
  const operationSequence = useRef(0);
  const successTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const onRefreshRef = useRef(onRefresh);
  const onTurnRef = useRef(onTurn);
  onRefreshRef.current = onRefresh;
  onTurnRef.current = onTurn;

  useEffect(() => {
    const controller = new AbortController();
    void service
      .listPendingConfirmations(controller.signal)
      .then((pending) => {
        setSessions((current) => mergePendingConfirmations(current, pending));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [service]);

  useEffect(() => () => {
    for (const timer of successTimers.current.values()) {
      clearTimeout(timer);
    }
  }, []);

  const session = sessions[conversationId] ?? emptySession();

  const setDraft = (value: string) => {
    setSessions((current) => updateSession(current, conversationId, (state) => ({
      ...state,
      draft: value,
    })));
  };

  const send = () => {
    const content = session.draft;
    if (
      content.trim().length === 0 ||
      sendingConversationIds.current.has(conversationId)
    ) {
      return;
    }

    const operationId = `send-${++operationSequence.current}`;
    sendingConversationIds.current.add(conversationId);
    setSessions((current) => updateSession(current, conversationId, (state) => ({
      ...state,
      draft: "",
      operation: {
        id: operationId,
        kind: "event",
        detail: "正在等待助手响应。",
        label: "发送",
        state: "pending",
        title: "正在发送消息",
      },
      sending: true,
    })));

    void service
      .sendMessage(conversationId, content)
      .then((turn) => {
        setSessions((current) => updateSession(
          current,
          conversationId,
          (state) => ({
            ...state,
            confirmations: turn.confirmation === null
              ? state.confirmations
              : upsertConfirmation(
                  state.confirmations,
                  turn.confirmation,
                  "awaiting",
                ),
            operation: turn.confirmation === null
              ? {
                  id: operationId,
                  kind: "event",
                  detail: "助手已返回响应。",
                  label: "发送",
                  state: "success",
                  title: "消息已发送",
                }
              : undefined,
          }),
        ));
        if (turn.confirmation === null) {
          scheduleSuccessRemoval(
            successTimers.current,
            operationId,
            conversationId,
            setSessions,
          );
        }
        onTurnRef.current(turn);
        onRefreshRef.current(conversationId);
      })
      .catch(() => {
        setSessions((current) => updateSession(
          current,
          conversationId,
          (state) => ({
            ...state,
            draft: state.draft.length > 0 ? state.draft : content,
            operation: {
              id: operationId,
              kind: "event",
              detail: "消息没有发送，草稿已恢复，可以重试。",
              label: "发送",
              state: "failure",
              title: "发送失败",
            },
          }),
        ));
      })
      .finally(() => {
        sendingConversationIds.current.delete(conversationId);
        setSessions((current) => updateSession(
          current,
          conversationId,
          (state) => ({ ...state, sending: false }),
        ));
      });
  };

  const decideConfirmation = (
    confirmationId: string,
    decision: ConfirmationDecision,
  ) => {
    const view = session.confirmations.find(
      (candidate) => candidate.confirmation.id === confirmationId,
    );
    if (
      view === undefined ||
      decidingConfirmationIds.current.has(confirmationId)
    ) {
      return;
    }

    decidingConfirmationIds.current.add(confirmationId);
    setConfirmationPhase(setSessions, conversationId, confirmationId, "deciding");
    void service
      .decideConfirmation(view.confirmation, decision)
      .then((turn) => {
        const phase = confirmationResultPhase(turn, decision);
        setSessions((current) => updateSession(
          current,
          conversationId,
          (state) => {
            const resolved = state.confirmations.map((candidate) =>
              candidate.confirmation.id === confirmationId
                ? { ...candidate, phase }
                : candidate
            );
            return {
              ...state,
              confirmations: turn.confirmation === null
                ? resolved
                : upsertConfirmation(resolved, turn.confirmation, "awaiting"),
            };
          },
        ));
        onTurnRef.current(turn);
        onRefreshRef.current(conversationId);
      })
      .catch(() => {
        setConfirmationPhase(
          setSessions,
          conversationId,
          confirmationId,
          "decision_failure",
        );
      })
      .finally(() => {
        decidingConfirmationIds.current.delete(confirmationId);
      });
  };

  return {
    confirmations: session.confirmations,
    decideConfirmation,
    draft: session.draft,
    operation: session.operation,
    send,
    sending: session.sending,
    setDraft,
  };
}

type SessionMap = Record<string, ConversationSessionState | undefined>;
type SetSessions = (
  update: (current: SessionMap) => SessionMap,
) => void;

function emptySession(): ConversationSessionState {
  return { confirmations: [], draft: "", sending: false };
}

function updateSession(
  sessions: SessionMap,
  conversationId: string,
  update: (state: ConversationSessionState) => ConversationSessionState,
): SessionMap {
  return {
    ...sessions,
    [conversationId]: update(sessions[conversationId] ?? emptySession()),
  };
}

function upsertConfirmation(
  confirmations: ConversationConfirmationView[],
  confirmation: PendingConfirmation,
  phase: ConversationConfirmationPhase,
): ConversationConfirmationView[] {
  const view = { confirmation, phase };
  const index = confirmations.findIndex(
    (candidate) => candidate.confirmation.id === confirmation.id,
  );
  if (index === -1) {
    return [...confirmations, view];
  }
  return confirmations.map((candidate, candidateIndex) =>
    candidateIndex === index ? view : candidate
  );
}

function mergePendingConfirmations(
  sessions: SessionMap,
  pending: PendingConfirmation[],
): SessionMap {
  return pending.reduce(
    (current, confirmation) => updateSession(
      current,
      confirmation.binding.conversationId,
      (state) => ({
        ...state,
        confirmations: upsertConfirmation(
          state.confirmations,
          confirmation,
          "awaiting",
        ),
      }),
    ),
    sessions,
  );
}

function setConfirmationPhase(
  setSessions: SetSessions,
  conversationId: string,
  confirmationId: string,
  phase: ConversationConfirmationPhase,
): void {
  setSessions((current) => updateSession(
    current,
    conversationId,
    (state) => ({
      ...state,
      confirmations: state.confirmations.map((candidate) =>
        candidate.confirmation.id === confirmationId
          ? { ...candidate, phase }
          : candidate
      ),
    }),
  ));
}

function confirmationResultPhase(
  turn: Turn,
  decision: ConfirmationDecision,
): ConversationConfirmationPhase {
  if (decision === "reject") {
    return "cancelled";
  }
  return turn.events.some((event) => event.type === "tool_execution_failed")
    ? "execution_failure"
    : "accepted";
}

function scheduleSuccessRemoval(
  timers: Map<string, ReturnType<typeof setTimeout>>,
  operationId: string,
  conversationId: string,
  setSessions: SetSessions,
): void {
  const timer = setTimeout(() => {
    timers.delete(operationId);
    setSessions((current) => updateSession(
      current,
      conversationId,
      (state) => ({
        ...state,
        operation: state.operation?.id === operationId
          ? undefined
          : state.operation,
      }),
    ));
  }, 2_000);
  timers.set(operationId, timer);
}
