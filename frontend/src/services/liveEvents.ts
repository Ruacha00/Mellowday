import type { ChatMessage } from "./conversationApi";

export interface EventSourcePort {
  addEventListener(
    type: string,
    listener: (event: MessageEvent<string>) => void,
  ): void;
  close(): void;
}

export interface LiveConversationEvent {
  kind: "reminder" | "proactive_chat";
  id: string;
  message: ChatMessage;
  occurredAt: number;
}

export interface LiveEventService {
  start(): void;
  subscribe(listener: (event: LiveConversationEvent) => void): () => void;
  close(): void;
}

interface LiveEventOptions {
  conversationId: string;
  startedAt: number;
  createEventSource?: (url: string) => EventSourcePort;
}

interface ApiReminderDelivery {
  reminder_id: string;
  role: "assistant";
  content: string;
  occurred_at: number;
}

interface ApiProactiveChatDelivery {
  proactive_chat_id: string;
  role: "assistant";
  content: string;
  occurred_at: number;
}

export class ApplicationLiveEventService implements LiveEventService {
  private readonly listeners = new Set<
    (event: LiveConversationEvent) => void
  >();
  private readonly deliveredReminderIds = new Set<string>();
  private readonly deliveredProactiveChatIds = new Set<string>();
  private source: EventSourcePort | null = null;

  constructor(private readonly options: LiveEventOptions) {}

  start(): void {
    if (this.source !== null) {
      return;
    }
    const path =
      `/api/conversations/${encodeURIComponent(this.options.conversationId)}` +
      `/live?after=${this.options.startedAt}`;
    const factory =
      this.options.createEventSource ??
      ((url: string) => new EventSource(url) as EventSourcePort);
    this.source = factory(path);
    this.source.addEventListener("reminder", (event) => {
      this.receiveReminder(JSON.parse(event.data) as ApiReminderDelivery);
    });
    this.source.addEventListener("proactive_chat", (event) => {
      this.receiveProactiveChat(
        JSON.parse(event.data) as ApiProactiveChatDelivery,
      );
    });
  }

  subscribe(listener: (event: LiveConversationEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  close(): void {
    this.source?.close();
    this.source = null;
  }

  private receiveReminder(delivery: ApiReminderDelivery): void {
    this.receiveUnique(this.deliveredReminderIds, {
      kind: "reminder",
      id: delivery.reminder_id,
      message: { role: delivery.role, content: delivery.content },
      occurredAt: delivery.occurred_at,
    });
  }

  private receiveProactiveChat(delivery: ApiProactiveChatDelivery): void {
    this.receiveUnique(this.deliveredProactiveChatIds, {
      kind: "proactive_chat",
      id: delivery.proactive_chat_id,
      message: { role: delivery.role, content: delivery.content },
      occurredAt: delivery.occurred_at,
    });
  }

  private receiveUnique(
    deliveredIds: Set<string>,
    event: LiveConversationEvent,
  ): void {
    if (deliveredIds.has(event.id)) {
      return;
    }
    deliveredIds.add(event.id);
    this.publish(event);
  }

  private publish(event: LiveConversationEvent): void {
    for (const listener of this.listeners) {
      listener(event);
    }
  }
}
