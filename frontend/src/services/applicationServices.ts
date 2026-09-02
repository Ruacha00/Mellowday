import {
  HttpConversationService,
  type ConversationService,
} from "./conversationApi";
import {
  ApplicationLiveEventService,
  type LiveEventService,
} from "./liveEvents";
import { HttpTaskService, type TaskService } from "./taskApi";

export interface ApplicationServices {
  conversation: ConversationService;
  liveEvents: LiveEventService;
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
    tasks: new HttpTaskService(),
  };
}

export const browserApplicationServices = createBrowserApplicationServices();
