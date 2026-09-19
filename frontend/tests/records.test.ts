import { describe, it, expect } from "vitest";
import {
  todayRecords,
  toLocalInput,
  isDone,
  statusLabel,
} from "../src/records/recordModel";
import type { LifeRecord } from "../src/api/types";
function record(patch: Partial<LifeRecord>): LifeRecord {
  return {
    id: "one",
    kind: "todos",
    title: "test",
    detail: "",
    due_at: null,
    status: "open",
    created_at: "",
    updated_at: "",
    meta: {},
    ...patch,
  };
}
describe("record projections", () => {
  it("matches the store's case-insensitive status filtering", () => {
    const now = new Date(2026, 8, 19, 12);
    const done = record({ status: "DONE", due_at: now.toISOString() });
    expect(isDone(done)).toBe(true);
    expect(todayRecords([done], now)).toEqual([]);
    expect(statusLabel("DONE")).toBe("已完成");
    expect(isDone(record({ kind: "memories", status: "SUPERSEDED" }))).toBe(
      true,
    );
  });
  it("only includes unfinished records on the local calendar day", () => {
    const now = new Date(2026, 8, 19, 12);
    const due = new Date(2026, 8, 19, 9).toISOString();
    expect(
      todayRecords(
        [
          record({ due_at: due }),
          record({ id: "done", due_at: due, status: "done" }),
          record({ id: "empty" }),
          record({ id: "next", due_at: new Date(2026, 8, 20).toISOString() }),
        ],
        now,
      ).map((r) => r.id),
    ).toEqual(["one"]);
  });
  it("superseded memories are inactive and local input preserves the instant", () => {
    expect(isDone(record({ kind: "memories", status: "superseded" }))).toBe(
      true,
    );
    const date = new Date(2026, 8, 19, 9, 30);
    expect(new Date(toLocalInput(date.toISOString())).getTime()).toBe(
      date.getTime(),
    );
  });
});
