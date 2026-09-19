import type { LifeRecord, RecordKind } from "../api/types";
export const recordLabels: Record<RecordKind, string> = {
  todos: "任务",
  calendar: "日历",
  reminders: "提醒",
  notes: "笔记",
  memories: "记忆",
};
export const rules: Record<
  RecordKind,
  { open: string; done: string; doneValues: string[] }
> = {
  todos: {
    open: "open",
    done: "done",
    doneValues: ["done", "completed", "cancelled", "archived", "deleted"],
  },
  calendar: {
    open: "scheduled",
    done: "done",
    doneValues: ["done", "completed", "cancelled", "archived", "deleted"],
  },
  reminders: {
    open: "scheduled",
    done: "done",
    doneValues: [
      "done",
      "delivered",
      "dismissed",
      "cancelled",
      "expired",
      "deleted",
    ],
  },
  notes: {
    open: "active",
    done: "archived",
    doneValues: ["archived", "deleted"],
  },
  memories: {
    open: "active",
    done: "expired",
    doneValues: ["expired", "deleted", "superseded"],
  },
};
export function isDone(record: LifeRecord) {
  return rules[record.kind].doneValues.includes(record.status.toLowerCase());
}
export function statusLabel(status: string) {
  return (
    (
      {
        open: "待完成",
        scheduled: "已安排",
        active: "生效中",
        done: "已完成",
        completed: "已完成",
        cancelled: "已取消",
        archived: "已归档",
        deleted: "已删除",
        expired: "已失效",
        superseded: "已被替代",
        delivered: "已送达",
        dismissed: "已忽略",
      } as Record<string, string>
    )[status.toLowerCase()] || status
  );
}
export function localTime(value?: string | null) {
  if (!value) return "未设置时间";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
}
export function toLocalInput(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
export function todayRecords(records: LifeRecord[], now = new Date()) {
  return records
    .filter((record) => {
      if (!record.due_at || isDone(record)) return false;
      const date = new Date(record.due_at);
      return (
        date.getFullYear() === now.getFullYear() &&
        date.getMonth() === now.getMonth() &&
        date.getDate() === now.getDate()
      );
    })
    .sort(
      (a, b) => new Date(a.due_at!).getTime() - new Date(b.due_at!).getTime(),
    );
}
