import {
  HttpConversationService,
  type ConversationService,
} from "./conversationApi";
import {
  ApplicationLiveEventService,
  type LiveEventService,
} from "./liveEvents";

export interface ApplicationServices {
  conversation: ConversationService;
  liveEvents: LiveEventService;
}

export function createBrowserApplicationServices(): ApplicationServices {
  const liveEvents = new ApplicationLiveEventService({
    conversationId: "main",
    startedAt: Date.now() / 1_000,
  });
  return {
    conversation: new HttpConversationService(),
    liveEvents,
  };
}

export const browserApplicationServices = createBrowserApplicationServices();
