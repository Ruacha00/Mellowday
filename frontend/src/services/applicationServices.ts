import {
  HttpConversationService,
  type ConversationService,
} from "./conversationApi";
import {
  ApplicationLiveEventService,
  type LiveEventService,
} from "./liveEvents";
import {
  HttpCalendarEventService,
  type CalendarEventService,
} from "./calendarEventApi";
import {
  HttpDailyReviewService,
  type DailyReviewService,
} from "./dailyReviewApi";
import { HttpNoteService, type NoteService } from "./noteApi";
import { HttpMemoryService, type MemoryService } from "./memoryApi";
import { HttpReminderService, type ReminderService } from "./reminderApi";
import { HttpPersonaService, type PersonaService } from "./personaApi";
import {
  HttpProactiveChatService,
  type ProactiveChatService,
} from "./proactiveChatApi";
import { HttpProviderService, type ProviderService } from "./providerApi";
import { HttpCapabilityService, type CapabilityService } from "./capabilityApi";
import { HttpTaskService, type TaskService } from "./taskApi";
import { HttpAuditService, type AuditService } from "./auditApi";
import {
  HttpDiagnosticsService,
  type DiagnosticsService,
} from "./diagnosticsApi";

export interface ApplicationServices {
  audit: AuditService;
  calendarEvents: CalendarEventService;
  capabilities: CapabilityService;
  conversation: ConversationService;
  dailyReview: DailyReviewService;
  diagnostics: DiagnosticsService;
  liveEvents: LiveEventService;
  memories: MemoryService;
  notes: NoteService;
  persona: PersonaService;
  proactiveChat: ProactiveChatService;
  providers: ProviderService;
  reminders: ReminderService;
  tasks: TaskService;
}

export function createBrowserApplicationServices(): ApplicationServices {
  const liveEvents = new ApplicationLiveEventService({
    conversationId: "main",
    startedAt: Date.now() / 1_000,
  });
  return {
    audit: new HttpAuditService(),
    calendarEvents: new HttpCalendarEventService(),
    capabilities: new HttpCapabilityService(),
    conversation: new HttpConversationService(),
    dailyReview: new HttpDailyReviewService(),
    diagnostics: new HttpDiagnosticsService(),
    liveEvents,
    memories: new HttpMemoryService(),
    notes: new HttpNoteService(),
    persona: new HttpPersonaService(),
    proactiveChat: new HttpProactiveChatService(),
    providers: new HttpProviderService(),
    reminders: new HttpReminderService(),
    tasks: new HttpTaskService(),
  };
}

export const browserApplicationServices = createBrowserApplicationServices();
