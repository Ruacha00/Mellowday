import { HttpResponseError } from "./conversationApi";

export type DailyReviewTaskTiming =
  | "overdue"
  | "due_today"
  | "upcoming"
  | "unscheduled";

export type DailyReviewReminderTiming = "overdue" | "upcoming";
export type DailyReviewCalendarTiming = "past" | "ongoing" | "upcoming";

export interface DailyReviewTask {
  id: string;
  title: string;
  details: string | null;
  deadline: string | null;
  timing: DailyReviewTaskTiming;
}

export interface DailyReviewReminder {
  id: string;
  message: string;
  dueAt: string;
  deliveryState: "scheduled" | "delivering" | "failed";
  taskId: string | null;
  timing: DailyReviewReminderTiming;
}

export interface DailyReviewCalendarEvent {
  id: string;
  title: string;
  startAt: string;
  endAt: string | null;
  details: string | null;
  timing: DailyReviewCalendarTiming;
}

export interface DailyReviewNote {
  id: string;
  title: string | null;
  content: string;
  updatedAt: number;
  relevance: "updated_today";
}

export interface DailyReview {
  date: string;
  timezone: string;
  generatedAt: number;
  tasks: DailyReviewTask[];
  reminders: DailyReviewReminder[];
  calendarEvents: DailyReviewCalendarEvent[];
  notes: DailyReviewNote[];
}

export interface DailyReviewService {
  getDailyReview(signal?: AbortSignal): Promise<DailyReview>;
}

interface ApiDailyReviewTask {
  id: string;
  title: string;
  details: string | null;
  deadline: string | null;
  timing: DailyReviewTaskTiming;
}

interface ApiDailyReviewReminder {
  id: string;
  message: string;
  due_at: string;
  delivery_state: "scheduled" | "delivering" | "failed";
  task_id: string | null;
  timing: DailyReviewReminderTiming;
}

interface ApiDailyReviewCalendarEvent {
  id: string;
  title: string;
  start_at: string;
  end_at: string | null;
  details: string | null;
  timing: DailyReviewCalendarTiming;
}

interface ApiDailyReviewNote {
  id: string;
  title: string | null;
  content: string;
  updated_at: number;
  relevance: "updated_today";
}

interface ApiDailyReview {
  date: string;
  timezone: string;
  generated_at: number;
  tasks: ApiDailyReviewTask[];
  reminders: ApiDailyReviewReminder[];
  calendar_events: ApiDailyReviewCalendarEvent[];
  notes: ApiDailyReviewNote[];
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function convertDailyReview(review: ApiDailyReview): DailyReview {
  return {
    date: review.date,
    timezone: review.timezone,
    generatedAt: review.generated_at,
    tasks: review.tasks.map((task) => ({ ...task })),
    reminders: review.reminders.map((reminder) => ({
      id: reminder.id,
      message: reminder.message,
      dueAt: reminder.due_at,
      deliveryState: reminder.delivery_state,
      taskId: reminder.task_id,
      timing: reminder.timing,
    })),
    calendarEvents: review.calendar_events.map((event) => ({
      id: event.id,
      title: event.title,
      startAt: event.start_at,
      endAt: event.end_at,
      details: event.details,
      timing: event.timing,
    })),
    notes: review.notes.map((note) => ({
      id: note.id,
      title: note.title,
      content: note.content,
      updatedAt: note.updated_at,
      relevance: note.relevance,
    })),
  };
}

export class HttpDailyReviewService implements DailyReviewService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async getDailyReview(signal?: AbortSignal): Promise<DailyReview> {
    const response = await this.fetchRequest(
      `${this.basePath}/api/settings/daily-review`,
      { signal },
    );
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    const payload = (await response.json()) as { daily_review: ApiDailyReview };
    return convertDailyReview(payload.daily_review);
  }
}
