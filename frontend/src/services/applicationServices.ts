import {
  HttpConversationService,
  type ConversationService,
} from "./conversationApi";
import {
  ApplicationLiveEventService,
  type LiveEventService,
} from "./liveEvents";
import { HttpReminderService, type ReminderService } from "./reminderApi";
import { HttpTaskService, type TaskService } from "./taskApi";

export interface ApplicationServices {
  conversation: ConversationService;
  liveEvents: LiveEventService;
  reminders: ReminderService;
  tasks: TaskService;
}

export function createBrowserApplicationServices(): ApplicationServices {
  const liveEvents = new ApplicationLiveEventService({
    conversationId: "main",
    startedAt: Date.now() / 1_000,
  });
  return {
    conversation: new HttpConversationService(),
    liveEvents,
    reminders: new HttpReminderService(),
    tasks: new HttpTaskService(),
  };
}

export const browserApplicationServices = createBrowserApplicationServices();
