import { useCallback, useEffect, useRef, useState } from "react";

import {
  DesktopTitleBarControls,
  ManagementPage,
  PageHeading,
  ProductNavigation,
} from "./appShell/AppShellNavigation";
import { getDesktopWindowControls } from "./appShell/desktopCapability";
import {
  RecentConversationDrawer,
  RecentConversationList,
} from "./appShell/RecentConversationViews";
import {
  recentConversationSummaries,
  recentConversationTitle,
  resolveActiveConversationId,
} from "./appShell/recentConversations";
import { canonicalizeHash, type AppRoute } from "./appShell/routeState";
import {
  loadWideNavigation,
  saveWideNavigation,
  toggleWideNavigation,
  type WideNavigation,
} from "./appShell/wideNavigationState";
import { AppearanceProvider, ThemeDecoration } from "./appearance/Appearance";
import {
  ConversationSurface,
  type ConversationEntry,
} from "./conversation/ConversationSurface";
import { useConversationSession } from "./conversation/useConversationSession";
import {
  browserApplicationServices,
  type ApplicationServices,
} from "./services/applicationServices";
import type { Conversation, ConversationSummary, Turn } from "./services/conversationApi";
import { LatestRequest } from "./services/requestLifecycle";

interface AppProps {
  services?: ApplicationServices;
}

export function App(props: AppProps) {
  return (
    <AppearanceProvider>
      <ApplicationShell {...props} />
    </AppearanceProvider>
  );
}

function ApplicationShell({ services = browserApplicationServices }: AppProps) {
  const [desktopWindowControls] = useState(() => getDesktopWindowControls());
  const [route, setRoute] = useState<AppRoute>(() =>
    canonicalizeHash(window.location.hash),
  );
  const [wideNavigation, setWideNavigation] = useState<WideNavigation>(() =>
    loadWideNavigation(window.localStorage),
  );
  const [activeConversationId, setActiveConversationId] = useState("main");
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversationSummaries, setConversationSummaries] = useState<
    ConversationSummary[]
  >([]);
  const [announcement, setAnnouncement] = useState<{
    id: string;
    text: string;
  } | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [recentDrawerOpen, setRecentDrawerOpen] = useState(false);
  const historyRequest = useRef(new LatestRequest());
  const activeConversationIdRef = useRef(activeConversationId);
  const announcementSequence = useRef(0);
  const recentDrawerTrigger = useRef<HTMLButtonElement>(null);
  const dockRecentDrawerTrigger = useRef<HTMLButtonElement>(null);
  const shellContent = useRef<HTMLDivElement>(null);
  activeConversationIdRef.current = activeConversationId;

  const refreshConversation = useCallback((showLoadingState: boolean) => {
    if (showLoadingState) {
      setLoadState("loading");
    }
    void historyRequest.current
      .run(async (signal) => {
        const summaries = await services.conversation.listConversations(signal);
        const sortedSummaries = recentConversationSummaries(summaries);
        const selectedId = resolveActiveConversationId(
          summaries,
          activeConversationId,
        );
        const selectedConversation = summaries.length > 0
          ? await services.conversation.loadConversation(selectedId, signal)
          : null;
        return {
          conversation: selectedConversation,
          selectedId,
          summaries: sortedSummaries,
        };
      })
      .then((result) => {
        if (result.status === "current") {
          setConversation(result.value.conversation);
          setConversationSummaries(result.value.summaries);
          setActiveConversationId(result.value.selectedId);
          setLoadState("ready");
        }
      })
      .catch(() => {
        setConversation(null);
        setLoadState("error");
      });
  }, [activeConversationId, services.conversation]);

  useEffect(() => {
    const syncRoute = () => {
      const nextRoute = canonicalizeHash(window.location.hash);
      if (window.location.hash !== nextRoute.hash) {
        window.history.replaceState(null, "", nextRoute.hash);
      }
      setRoute(nextRoute);
    };
    syncRoute();
    window.addEventListener("hashchange", syncRoute);
    return () => window.removeEventListener("hashchange", syncRoute);
  }, []);

  useEffect(() => {
    refreshConversation(true);
    return () => historyRequest.current.cancel();
  }, [refreshConversation]);

  useEffect(() => {
    const unsubscribe = services.liveEvents.subscribe((event) => {
      if (event.kind === "proactive_chat") {
        setAnnouncement({
          id: `live-${++announcementSequence.current}`,
          text: `主动聊天：${event.message.content}`,
        });
      }
      refreshConversation(false);
    });
    services.liveEvents.start();
    return unsubscribe;
  }, [refreshConversation, services.liveEvents]);

  useEffect(() => {
    if (shellContent.current !== null) {
      shellContent.current.inert = recentDrawerOpen;
    }
    return () => {
      if (shellContent.current !== null) {
        shellContent.current.inert = false;
      }
    };
  }, [recentDrawerOpen]);

  const toggleNavigation = () => {
    const nextState = toggleWideNavigation(wideNavigation);
    setWideNavigation(nextState);
    saveWideNavigation(window.localStorage, nextState);
  };
  const closeRecentDrawer = useCallback(() => {
    setRecentDrawerOpen(false);
    window.requestAnimationFrame(() => {
      const narrowTrigger = recentDrawerTrigger.current;
      const restoreTarget = narrowTrigger?.offsetParent === null
        ? dockRecentDrawerTrigger.current
        : narrowTrigger;
      restoreTarget?.focus();
    });
  }, []);
  const selectConversation = useCallback((conversationId: string) => {
    activeConversationIdRef.current = conversationId;
    setActiveConversationId(conversationId);
    if (window.location.hash !== "#/conversation") {
      window.location.hash = "#/conversation";
    }
  }, []);
  const renameConversation = useCallback(async (
    summary: ConversationSummary,
    title: string,
  ) => {
    const updated = await services.conversation.renameConversation(
      summary.conversationId,
      title,
    );
    setConversationSummaries((current) => current.map((item) => (
      item.conversationId === updated.conversationId ? updated : item
    )));
    setConversation((current) => current?.summary.conversationId === updated.conversationId
      ? { ...current, summary: updated }
      : current);
  }, [services.conversation]);
  const deleteConversation = useCallback(async (summary: ConversationSummary) => {
    const confirmation = await services.conversation.requestResetConfirmation(
      summary.conversationId,
    );
    const result = await services.conversation.decideReset(confirmation, "accept");
    if (!result.ok || result.decision !== "accept") {
      throw new Error("Conversation deletion was not accepted");
    }
    const remaining = conversationSummaries.filter(
      (item) => item.conversationId !== summary.conversationId,
    );
    setConversationSummaries(remaining);
    if (activeConversationIdRef.current === summary.conversationId) {
      const nextId = remaining[0]?.conversationId ?? "main";
      activeConversationIdRef.current = nextId;
      setActiveConversationId(nextId);
      setConversation(null);
      setLoadState(remaining.length === 0 ? "ready" : "loading");
    }
    refreshConversation(false);
  }, [conversationSummaries, refreshConversation, services.conversation]);

  const announceTurn = (turn: Turn) => {
    if (turn.chatContent.content.length === 0) {
      return;
    }
    setAnnouncement({
      id: `turn-${++announcementSequence.current}`,
      text: `Mellowday：${turn.chatContent.content}`,
    });
  };

  const conversationSession = useConversationSession({
    conversationId: activeConversationId,
    onRefresh: (conversationId) => {
      if (activeConversationIdRef.current === conversationId) {
        refreshConversation(false);
      }
    },
    onTurn: announceTurn,
    service: services.conversation,
  });

  const storedEntries: ConversationEntry[] = (conversation?.messages ?? []).map(
    (message, index) => ({
      id: `stored-${index}`,
      kind: "message",
      message,
    }),
  );
  const operationEntry = conversationSession.operation;
  const conversationEntries = operationEntry === undefined
    ? storedEntries
    : [...storedEntries, operationEntry];

  return (
    <div className="app-frame" data-wide-navigation={wideNavigation}>
      <ThemeDecoration />
      <p
        aria-atomic="true"
        aria-live="polite"
        className="visually-hidden"
        role="status"
      >
        {announcement === null
          ? ""
          : <span key={announcement.id}>{announcement.text}</span>}
      </p>
      <div className="shell-content" data-shell-content ref={shellContent}>
        <header
          className={desktopWindowControls === null
            ? "title-bar"
            : "title-bar has-window-controls"}
        >
          <a className="brand-lockup" href="#/conversation" aria-label="Mellowday 对话首页">
            <span aria-hidden="true" className="brand-orb" />
            <span>Mellowday</span>
          </a>
          <span className="local-status"><i aria-hidden="true" />本地运行</span>
          {desktopWindowControls === null ? null : (
            <DesktopTitleBarControls controls={desktopWindowControls} />
          )}
        </header>

        <div className="shell-layout">
          <ProductNavigation route={route} wideNavigation={wideNavigation} />
          <button
            aria-expanded={wideNavigation === "rail"}
            className="rail-toggle"
            onClick={toggleNavigation}
            title={wideNavigation === "rail" ? "收起导航" : "展开导航"}
            type="button"
          >
            <span aria-hidden="true">{wideNavigation === "rail" ? "«" : "»"}</span>
            <span>{wideNavigation === "rail" ? "收起导航" : "展开导航"}</span>
          </button>

          <section className="recent-rail" aria-labelledby="recent-rail-title">
            <div className="rail-section-heading">
              <h2 id="recent-rail-title">最近对话</h2>
              <span>{conversationSummaries.length}</span>
            </div>
            <RecentConversationList
              activeConversationId={activeConversationId}
              onDelete={deleteConversation}
              onRename={renameConversation}
              onSelect={selectConversation}
              summaries={conversationSummaries}
            />
          </section>
          <button
            aria-haspopup="dialog"
            aria-label="最近对话"
            className="dock-recent-trigger"
            onClick={() => setRecentDrawerOpen(true)}
            ref={dockRecentDrawerTrigger}
            title="最近对话"
            type="button"
          >
            <span aria-hidden="true">☰</span>
          </button>

          <main
            className={`page-surface${
              route.area === "conversation" ? " page-surface-conversation" : ""
            }`}
          >
            <PageHeading
              onOpenRecent={() => setRecentDrawerOpen(true)}
              recentTriggerRef={recentDrawerTrigger}
              route={route}
            />
            {route.area === "conversation" ? (
              <ConversationSurface
                confirmations={conversationSession.confirmations}
                conversationId={activeConversationId}
                conversationTitle={conversation === null
                  ? "今天，慢慢来"
                  : recentConversationTitle(conversation.summary)}
                draft={conversationSession.draft}
                entries={conversationEntries}
                loadState={loadState}
                onConfirmationDecision={conversationSession.decideConfirmation}
                onDraftChange={conversationSession.setDraft}
                onSend={conversationSession.send}
                sending={conversationSession.sending}
              />
            ) : (
              <ManagementPage
                auditService={services.audit}
                calendarEventService={services.calendarEvents}
                capabilityService={services.capabilities}
                conversationService={services.conversation}
                dailyReviewService={services.dailyReview}
                diagnosticsService={services.diagnostics}
                memoryService={services.memories}
                noteService={services.notes}
                onConversationHistoryChange={() => refreshConversation(false)}
                personaService={services.persona}
                proactiveChatService={services.proactiveChat}
                providerService={services.providers}
                reminderService={services.reminders}
                route={route}
                taskService={services.tasks}
              />
            )}
          </main>
        </div>
      </div>
      {recentDrawerOpen ? (
        <RecentConversationDrawer
          activeConversationId={activeConversationId}
          onClose={closeRecentDrawer}
          onDelete={async (summary) => {
            const deletedActiveConversation = summary.conversationId === activeConversationIdRef.current;
            await deleteConversation(summary);
            if (deletedActiveConversation) closeRecentDrawer();
          }}
          onRename={renameConversation}
          onSelect={(conversationId) => {
            selectConversation(conversationId);
            closeRecentDrawer();
          }}
          summaries={conversationSummaries}
        />
      ) : null}
    </div>
  );
}
