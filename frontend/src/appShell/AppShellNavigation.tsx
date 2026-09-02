import { lazy, Suspense, type RefObject } from "react";

import { AppearanceControls, AppearancePopover } from "../appearance/Appearance";
import { LifeCalendarPage } from "../life/LifeCalendarPage";
import { LifeNotesPage } from "../life/LifeNotesPage";
import { LifeRemindersPage } from "../life/LifeRemindersPage";
import { LifeTasksPage } from "../life/LifeTasksPage";
import { MemoryManagementPage } from "../memory/MemoryManagementPage";
import { PersonaSettingsPage } from "../settings/PersonaSettingsPage";
import { ProactiveChatSettingsPage } from "../settings/ProactiveChatSettingsPage";
import { ProviderSettingsPage } from "../settings/ProviderSettingsPage";
import { CapabilitySettingsPage } from "../settings/CapabilitySettingsPage";
import { ConversationHistoryPage } from "../settings/ConversationHistoryPage";
import { DiagnosticsPage } from "../settings/DiagnosticsPage";
import { OperationRecordsPage } from "../settings/OperationRecordsPage";
import type { AuditService } from "../services/auditApi";
import type { CalendarEventService } from "../services/calendarEventApi";
import type { CapabilityService } from "../services/capabilityApi";
import type { ConversationService } from "../services/conversationApi";
import type { DailyReviewService } from "../services/dailyReviewApi";
import type { DiagnosticsService } from "../services/diagnosticsApi";
import type { MemoryService } from "../services/memoryApi";
import type { NoteService } from "../services/noteApi";
import type { PersonaService } from "../services/personaApi";
import type { ProactiveChatService } from "../services/proactiveChatApi";
import type { ProviderService } from "../services/providerApi";
import type { ReminderService } from "../services/reminderApi";
import type { TaskService } from "../services/taskApi";
import { TodayPage } from "../today/TodayPage";
import type { DesktopWindowControls } from "./desktopCapability";
import {
  lifeDestinations,
  pageDetails,
  placeholderCards,
  primaryDestinations,
  settingsDestinations,
} from "./navigationModel";
import type { AppRoute } from "./routeState";
import type { WideNavigation } from "./wideNavigationState";

const ManagementDetails = lazy(() => import("./ManagementDetails"));

export function DesktopTitleBarControls({
  controls,
}: {
  controls: DesktopWindowControls;
}) {
  return (
    <div aria-label="窗口控制" className="window-controls" role="group">
      <button aria-label="最小化窗口" onClick={() => controls.minimize()} type="button">
        <span aria-hidden="true">—</span>
      </button>
      <button
        aria-label="切换最大化窗口"
        onClick={() => controls.toggleMaximize()}
        type="button"
      >
        <span aria-hidden="true">□</span>
      </button>
      <button aria-label="关闭窗口" onClick={() => controls.close()} type="button">
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}

export function ProductNavigation({
  route,
  wideNavigation,
}: {
  route: AppRoute;
  wideNavigation: WideNavigation;
}) {
  return (
    <nav aria-label="产品区域" className="product-navigation">
      <div className="rail-identity" aria-hidden={wideNavigation === "dock"}>
        <strong>Mellowday</strong>
        <span>慢慢过日子，也好好记得你。</span>
      </div>
      <div className="primary-links">
        {primaryDestinations.map((destination) => (
          <a
            aria-current={route.area === destination.area ? "page" : undefined}
            className="primary-link"
            href={destination.hash}
            key={destination.area}
            title={destination.label}
          >
            <span aria-hidden="true" className="primary-icon">{destination.icon}</span>
            <span className="primary-label">{destination.label}</span>
          </a>
        ))}
      </div>
    </nav>
  );
}

export function PageHeading({
  onOpenRecent,
  recentTriggerRef,
  route,
}: {
  onOpenRecent: () => void;
  recentTriggerRef: RefObject<HTMLButtonElement | null>;
  route: AppRoute;
}) {
  const page = pageDetails(route);
  return (
    <header className="page-heading">
      <div>
        <p className="page-kicker">{page.kicker}</p>
        <h1 tabIndex={-1}>{page.title}</h1>
        <p>{page.note}</p>
      </div>
      <div className="page-actions">
        {route.area === "conversation" ? (
          <button
            aria-haspopup="dialog"
            className="recent-drawer-trigger"
            onClick={onOpenRecent}
            ref={recentTriggerRef}
            type="button"
          >
            最近对话
          </button>
        ) : null}
        <AppearancePopover />
      </div>
    </header>
  );
}

export function ManagementPage({
  auditService,
  calendarEventService,
  capabilityService,
  conversationService,
  dailyReviewService,
  diagnosticsService,
  memoryService,
  noteService,
  onConversationHistoryChange,
  personaService,
  proactiveChatService,
  providerService,
  reminderService,
  route,
  taskService,
}: {
  auditService: AuditService;
  calendarEventService: CalendarEventService;
  capabilityService: CapabilityService;
  conversationService: ConversationService;
  dailyReviewService: DailyReviewService;
  diagnosticsService: DiagnosticsService;
  memoryService: MemoryService;
  noteService: NoteService;
  onConversationHistoryChange: () => void;
  personaService: PersonaService;
  proactiveChatService: ProactiveChatService;
  providerService: ProviderService;
  reminderService: ReminderService;
  route: AppRoute;
  taskService: TaskService;
}) {
  const destinations = route.area === "life"
    ? lifeDestinations
    : route.area === "settings"
      ? settingsDestinations
      : [];
  const activeDestination = destinations.find(
    (destination) => destination.hash === route.hash,
  );
  const isAppearancePage = route.hash === "#/settings/appearance";

  return (
    <section className="management-page">
      {destinations.length > 0 ? (
        <nav
          aria-label={`${route.area === "life" ? "生活" : "设置"}二级导航`}
          className="secondary-navigation"
        >
          {destinations.map((destination) => (
            <a
              aria-current={destination.hash === route.hash ? "page" : undefined}
              href={destination.hash}
              key={destination.hash}
            >
              {destination.label}
            </a>
          ))}
        </nav>
      ) : null}
      {route.hash === "#/today" ? (
        <TodayPage reviewService={dailyReviewService} taskService={taskService} />
      ) : route.hash === "#/life/tasks" ? (
        <LifeTasksPage service={taskService} />
      ) : route.hash === "#/life/reminders" ? (
        <LifeRemindersPage service={reminderService} />
      ) : route.hash === "#/life/calendar" ? (
        <LifeCalendarPage service={calendarEventService} />
      ) : route.hash === "#/life/notes" ? (
        <LifeNotesPage service={noteService} />
      ) : route.hash === "#/memory" ? (
        <MemoryManagementPage service={memoryService} />
      ) : route.hash === "#/settings/persona" ? (
        <PersonaSettingsPage service={personaService} />
      ) : route.hash === "#/settings/proactive-chat" ? (
        <ProactiveChatSettingsPage service={proactiveChatService} />
      ) : route.hash === "#/settings/providers" ? (
        <ProviderSettingsPage service={providerService} />
      ) : route.hash === "#/settings/capabilities" ? (
        <CapabilitySettingsPage service={capabilityService} />
      ) : route.hash === "#/settings/history" ? (
        <ConversationHistoryPage
          onHistoryChanged={onConversationHistoryChange}
          service={conversationService}
        />
      ) : route.hash === "#/settings/audit" ? (
        <OperationRecordsPage service={auditService} />
      ) : route.hash === "#/settings/diagnostics" ? (
        <DiagnosticsPage service={diagnosticsService} />
      ) : isAppearancePage ? (
        <AppearanceControls />
      ) : (
        <Suspense fallback={<p className="management-loading">正在载入页面内容…</p>}>
          <ManagementDetails
            cards={placeholderCards(route)}
            description={activeDestination?.description ?? pageDetails(route).description}
          />
        </Suspense>
      )}
    </section>
  );
}
