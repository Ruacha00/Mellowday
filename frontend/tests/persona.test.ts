import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import PersonaPage from "../src/settings/PersonaPage.vue";
const persona = {
  name: "MellowDay",
  identity: "伙伴",
  character: "温和",
  speaking_style: "自然",
  relationship: "平等",
  boundaries: "真实",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());
it("keeps the draft on failure and reports only acknowledged saves", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json(persona))
    .mockResolvedValueOnce(json({ detail: "保存失败" }, 500))
    .mockResolvedValueOnce(json({ ...persona, name: "小悠" }));
  vi.stubGlobal("fetch", fetcher);
  const page = mount(PersonaPage);
  await flushPromises();
  await page.get("input").setValue("小悠");
  await page.get("form").trigger("submit");
  await flushPromises();
  expect(page.get('[role="alert"]').text()).toContain("保存失败");
  expect(page.get("input").element.value).toBe("小悠");
  await page.get("form").trigger("submit");
  await flushPromises();
  expect(page.get('[role="status"]').text()).toContain("下一轮");
  expect(JSON.parse(fetcher.mock.calls[2][1].body).name).toBe("小悠");
  page.unmount();
});
it("does not expose a save form when initial load fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(json({ detail: "配置损坏" }, 409)),
  );
  const page = mount(PersonaPage);
  await flushPromises();
  expect(page.find("form").exists()).toBe(false);
  expect(page.get('[role="alert"]').text()).toContain("配置损坏");
  page.unmount();
});
