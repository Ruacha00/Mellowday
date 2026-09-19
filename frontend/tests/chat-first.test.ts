import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, onMounted } from "vue";
import CalendarDrawer from "../src/calendar/CalendarDrawer.vue";
import PersonaAdaptation from "../src/settings/PersonaAdaptation.vue";
import { calendarTarget } from "../src/calendar/calendarState";
import { instant, localInput } from "../src/calendar/calendarDates";
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
afterEach(() => {
  vi.unstubAllGlobals();
  calendarTarget.value = {};
});
const item = {
  id: "event-1",
  title: "讨论",
  detail: "",
  start_at: "2026-09-21T10:00:00+08:00",
  end_at: "2026-09-21T11:00:00+08:00",
  occurrence_start: "2026-09-21T10:00:00+08:00",
  all_day: false,
  timezone: "Asia/Shanghai",
  recurrence: "weekly",
  reminder_minutes: 10,
  status: "scheduled",
};
vi.mock("@fullcalendar/vue3", async () => {
  const { defineComponent, onMounted } = await import("vue");
  return {
    default: defineComponent({
      props: ["options"],
      setup(props) {
        onMounted(() =>
          props.options.datesSet({
            startStr: "2026-09-01T00:00:00+08:00",
            endStr: "2026-10-01T00:00:00+08:00",
          }),
        );
        return {};
      },
      template: `<button class="open-event" @click="options.eventClick({event:{extendedProps:{record:options.events[0].extendedProps.record}}})">open</button>`,
    }),
  };
});

it("preserves original occurrence, zone and scope when saving a recurrence", async () => {
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") return json({ event: item });
    return json(
      path.includes("subscriptions")
        ? { subscriptions: [] }
        : { events: [item] },
    );
  });
  vi.stubGlobal("fetch", fetcher);
  const page = mount(CalendarDrawer);
  await flushPromises();
  await page.get(".open-event").trigger("click");
  await page.get('input[maxlength="200"]').setValue("新的标题");
  await page.get("form").trigger("submit");
  await flushPromises();
  const call = fetcher.mock.calls.find((c) => c[1]?.method === "PUT")!;
  expect(call[0]).toContain("scope=single");
  expect(decodeURIComponent(call[0])).toContain(
    "occurrence_start=2026-09-21T10:00:00+08:00",
  );
  expect(JSON.parse(call[1]!.body as string).title).toBe("新的标题");
  expect(JSON.parse(call[1]!.body as string).start_at).toBe(
    "2026-09-21T10:00:00.000+08:00",
  );
  expect(page.find("form").exists()).toBe(false);
  page.unmount();
});
it("retains calendar draft when server rejects save", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? json({ detail: "此事项已经变更" }, 409)
        : json(
            path.includes("subscriptions")
              ? { subscriptions: [] }
              : { events: [item] },
          ),
    ),
  );
  const page = mount(CalendarDrawer);
  await flushPromises();
  await page.get(".open-event").trigger("click");
  await page.get('input[maxlength="200"]').setValue("保留草稿");
  await page.get("form").trigger("submit");
  await flushPromises();
  expect(page.get("[role=alert]").text()).toContain("已经变更");
  expect(
    (page.get('input[maxlength="200"]').element as HTMLInputElement).value,
  ).toBe("保留草稿");
  page.unmount();
});
it("converts selected timezone wall clock and rejects DST gaps", () => {
  expect(instant("2026-09-21T10:00", "Asia/Shanghai")).toBe(
    "2026-09-21T10:00:00.000+08:00",
  );
  expect(localInput("2026-09-21T02:00:00Z", "Asia/Shanghai")).toBe(
    "2026-09-21T10:00",
  );
  expect(() => instant("2026-03-08T02:30", "America/New_York")).toThrow(
    "时间无效",
  );
});
it("reconciles pause and undo with persisted snapshot", async () => {
  const rule = {
    id: "r1",
    scene: "倾诉",
    behavior: "先倾听",
    example: "",
    enabled: true,
    locked: false,
    source: [{ quote: "先听我说", created_at: "2026-09-19T00:00:00Z" }],
    created_at: "2026-09-19T00:00:00Z",
  };
  let paused = false;
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") paused = JSON.parse(init.body as string).paused;
    if (path.endsWith("/undo")) rule.enabled = false;
    return json({ paused, version: 1, rules: [rule], history: [] });
  });
  vi.stubGlobal("fetch", fetcher);
  const page = mount(PersonaAdaptation);
  await flushPromises();
  await page
    .findAll("button")
    .find((b) => b.text() === "暂停演化")!
    .trigger("click");
  await flushPromises();
  expect(page.text()).toContain("已暂停自动更新");
  await page
    .findAll("button")
    .find((b) => b.text() === "撤销习惯")!
    .trigger("click");
  await flushPromises();
  expect(page.text()).toContain("已停用");
  expect(fetcher.mock.calls.some((c) => c[0].endsWith("/r1/undo"))).toBe(true);
  page.unmount();
});
