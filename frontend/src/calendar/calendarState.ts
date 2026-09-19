import { ref } from "vue";
export const calendarOpen = ref(false);
export const calendarTarget = ref<{ eventId?: string; date?: string }>({});
export function openCalendar(eventId?: string, date?: string) {
  calendarTarget.value = { eventId, date };
  calendarOpen.value = true;
}
export interface CalendarEvent {
  id: string;
  title: string;
  detail: string;
  start_at: string;
  end_at: string;
  occurrence_start?: string;
  all_day: boolean;
  timezone: string;
  recurrence: string;
  reminder_minutes: number | null;
  status: string;
}
export interface Subscription {
  id: string;
  title: string;
  time: string;
  timezone: string;
  recurrence: string;
  weekday?: number;
  session_id: string;
  enabled: boolean;
  last_error?: string;
}
export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string;
  event_id?: string;
  event_ids?: string[];
  session_id?: string;
  scheduled_at: string;
  occurrence_start?: string;
  read: boolean;
}
