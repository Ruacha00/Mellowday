import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import NotificationBubbles from "../src/calendar/NotificationBubbles.vue";
import { calendarOpen, calendarTarget } from "../src/calendar/calendarState";
const notice = {
  id: "n1",
  kind: "reminder",
  title: "开会",
  body: "会议快开始了",
  event_id: "event1",
  scheduled_at: "2026-09-21T10:00:00+08:00",
  occurrence_start: "2026-09-21T10:00:00+08:00",
  read: false,
};
afterEach(() => {
  vi.unstubAllGlobals();
  calendarOpen.value = false;
  calendarTarget.value = {};
});
it("opens reminder calendar target then acknowledges the notification without mutating event", async () => {
  const fetcher = vi.fn(
    async (_url: string, init?: RequestInit) =>
      new Response(
        JSON.stringify(
          init?.method ? { ok: true } : { notifications: [notice] },
        ),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", component: { template: "<p />" } }],
  });
  await router.push("/");
  const page = mount(NotificationBubbles, { global: { plugins: [router] } });
  await flushPromises();
  expect(page.text()).toContain("会议快开始了");
  await page.get(".notification-body").trigger("click");
  await flushPromises();
  expect(calendarOpen.value).toBe(true);
  expect(calendarTarget.value.eventId).toBe("event1");
  expect(page.find(".notification-bubble").exists()).toBe(false);
  expect(
    fetcher.mock.calls.filter((c) => c[1]?.method).map((c) => c[0]),
  ).toEqual(["/api/calendar/notifications/n1/read"]);
  page.unmount();
});
it("keeps unread bubble when acknowledgment fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (_url: string, init?: RequestInit) =>
        new Response(
          JSON.stringify(
            init?.method
              ? { detail: "保存已读失败" }
              : { notifications: [notice] },
          ),
          { status: init?.method ? 500 : 200 },
        ),
    ),
  );
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", component: { template: "<p />" } }],
  });
  await router.push("/");
  const page = mount(NotificationBubbles, { global: { plugins: [router] } });
  await flushPromises();
  await page.get('[aria-label="标记已读"]').trigger("click");
  await flushPromises();
  expect(page.find(".notification-bubble").exists()).toBe(true);
  expect(page.text()).toContain("保存已读失败");
  page.unmount();
});
