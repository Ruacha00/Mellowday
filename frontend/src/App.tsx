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
} from "./appShell/recentConversations";
import { canonicalizeHash, type AppRoute } from "./appShell/routeState";
import {
  loadWideNavigation,
  saveWideNavigation,
  toggleWideNavigation,
  type WideNavigation,
} from "./appShell/wideNavigationState";
import { AppearanceProvider, ThemeDecoration } from "./appearance/Appearance";
import { ConversationSurface } from "./conversation/ConversationSurface";
import {
  browserApplicationServices,
  type ApplicationServices,
} from "./services/applicationServices";
import type { Conversation, ConversationSummary } from "./services/conversationApi";
import type { LiveConversationEvent } from "./services/liveEvents";
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
  const [latestLiveEvent, setLatestLiveEvent] =
    useState<LiveConversationEvent | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [recentDrawerOpen, setRecentDrawerOpen] = useState(false);
  const historyRequest = useRef(new LatestRequest());
  const recentDrawerTrigger = useRef<HTMLButtonElement>(null);
  const dockRecentDrawerTrigger = useRef<HTMLButtonElement>(null);
  const shellContent = useRef<HTMLDivElement>(null);

  const refreshConversation = useCallback((showLoadingState: boolean) => {
    if (showLoadingState) {
      setLoadState("loading");
    }
    void historyRequest.current
      .run(async (signal) => {
        const summaries = await services.conversation.listConversations(signal);
        const sortedSummaries = recentConversationSummaries(summaries);
        const selectedId = sortedSummaries.some(
          (summary) => summary.conversationId === activeConversationId,
        )
          ? activeConversationId
          : sortedSummaries[0]?.conversationId ?? activeConversationId;
        const selectedConversation = sortedSummaries.length > 0
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
      setLatestLiveEvent(event);
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
    setActiveConversationId(conversationId);
    if (window.location.hash !== "#/conversation") {
      window.location.hash = "#/conversation";
    }
  }, []);

  return (
    <div className="app-frame" data-wide-navigation={wideNavigation}>
      <ThemeDecoration />
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
                conversationId={activeConversationId}
                conversationTitle={conversation === null
                  ? "今天，慢慢来"
                  : recentConversationTitle(conversation.summary)}
                latestLiveEvent={activeConversationId === "main"
                  ? latestLiveEvent
                  : null}
                loadState={loadState}
                messages={conversation?.messages ?? []}
              />
            ) : (
              <ManagementPage route={route} />
            )}
          </main>
        </div>
      </div>
      {recentDrawerOpen ? (
        <RecentConversationDrawer
          activeConversationId={activeConversationId}
          onClose={closeRecentDrawer}
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
