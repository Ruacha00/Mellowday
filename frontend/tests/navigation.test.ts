import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";
import { useConversation } from "../src/conversation/useConversation";

vi.mock("../src/appearance/useAppearance", async () => {
  const { ref } = await import("vue");
  return {
    useAppearance: () => ({ theme: ref({ label: "晴空", assets: null }) }),
  };
});
vi.mock("../src/conversation/useConversation", async () => {
  const { ref } = await import("vue");
  const state = {
    sessionId: ref(null),
    sessions: ref([{ session_id: "one", title: "已有会话" }]),
    sessionsLoading: ref(false),
    sessionsError: ref(""),
    error: ref("读取失败"),
    busy: ref(false),
    pendingConfirmation: ref(null),
    refreshSessions: vi.fn(),
    selectSession: vi.fn(),
    newSession: vi.fn(),
  };
  return { useConversation: () => state };
});
beforeEach(() => vi.mocked(useConversation().selectSession).mockReset());
async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/:pathMatch(.*)*", component: { template: "<p>其他页面</p>" } },
      { path: "/today", component: { template: "<p>今日页</p>" } },
      { path: "/conversation", component: { template: "<p>对话页</p>" } },
      {
        path: "/settings/appearance",
        component: { template: "<p>外观页</p>" },
      },
    ],
  });
  await router.push("/today");
  const page = mount(App, { global: { plugins: [router] } });
  return { router, page };
}
describe("recent session navigation", () => {
  it("keeps the user's later navigation when a slow session finishes loading", async () => {
    let finish!: (value: boolean) => void;
    vi.mocked(useConversation().selectSession).mockReturnValue(
      new Promise((r) => {
        finish = r;
      }),
    );
    const { router, page } = await setup();
    await page.get(".session-link").trigger("click");
    await router.push("/settings/appearance");
    finish(true);
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/settings/appearance");
    page.unmount();
  });
  it("shows a failed selection without redirecting", async () => {
    vi.mocked(useConversation().selectSession).mockResolvedValue(false);
    const { router, page } = await setup();
    await page.get(".session-link").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/today");
    expect(page.get("[role=alert]").text()).toBe("读取失败");
    page.unmount();
  });
  it("opens a successfully selected session", async () => {
    vi.mocked(useConversation().selectSession).mockResolvedValue(true);
    const { router, page } = await setup();
    await page.get(".session-link").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/conversation");
    page.unmount();
  });
});
