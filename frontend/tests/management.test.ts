import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import RecordsPage from "../src/records/RecordsPage.vue";
import SkillsPage from "../src/skills/SkillsPage.vue";
import ModelSettingsPage from "../src/settings/ModelSettingsPage.vue";

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
afterEach(() => vi.unstubAllGlobals());
describe("management writes and receipts", () => {
  it("keeps post-write skill state when an older list refresh finishes last", async () => {
    const enabled = {
      name: "one",
      description: "规则",
      enabled: true,
      version: "0.1.0",
      body: "one",
    };
    const disabled = { ...enabled, enabled: false };
    let finish!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(json({ skills: [enabled] }))
        .mockResolvedValueOnce(json(enabled))
        .mockResolvedValueOnce(json({ versions: [] }))
        .mockImplementationOnce(
          () =>
            new Promise<Response>((resolve) => {
              finish = resolve;
            }),
        )
        .mockResolvedValueOnce(json({ ok: true }))
        .mockResolvedValueOnce(json(disabled))
        .mockResolvedValueOnce(json({ versions: [] }))
        .mockResolvedValueOnce(json({ skills: [disabled] })),
    );
    const page = mount(SkillsPage);
    await flushPromises();
    await page.get(".skill-item").trigger("click");
    await flushPromises();
    await page
      .findAll("button")
      .find((b) => b.text() === "刷新")!
      .trigger("click");
    await page
      .findAll("button")
      .find((b) => b.text() === "停用")!
      .trigger("click");
    await flushPromises();
    finish(json({ skills: [enabled] }));
    await flushPromises();
    expect(page.get(".skill-item .badge").text()).toContain("已停用");
    expect(page.get(".skill-detail").text()).toContain("启用");
    page.unmount();
  });
  it("retains the record draft after a rejected save without retrying", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json({ records: [] }))
      .mockResolvedValueOnce(json({ detail: "拒绝写入" }, 400));
    vi.stubGlobal("fetch", fetcher);
    const page = mount(RecordsPage, { props: { kind: "todos" } });
    await flushPromises();
    await page
      .findAll("button")
      .find((b) => b.text() === "新建任务")!
      .trigger("click");
    await page.find(".record-editor input").setValue("不要丢失的草稿");
    await page.find(".record-editor").trigger("submit");
    await flushPromises();
    expect(
      (page.find(".record-editor input").element as HTMLInputElement).value,
    ).toBe("不要丢失的草稿");
    expect(page.get("[role=alert]").text()).toBe("拒绝写入");
    expect(fetcher).toHaveBeenCalledTimes(2);
    page.unmount();
  });
  it("shows an undo conflict without a success message or a repeated POST", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json({ records: [] }))
      .mockResolvedValueOnce(json({ operation_id: "op1" }))
      .mockResolvedValueOnce(json({ records: [] }))
      .mockResolvedValueOnce(json({ detail: "记录已被后续修改" }, 409));
    vi.stubGlobal("fetch", fetcher);
    const page = mount(RecordsPage, { props: { kind: "notes" } });
    await flushPromises();
    await page
      .findAll("button")
      .find((b) => b.text() === "新建笔记")!
      .trigger("click");
    await page.find(".record-editor input").setValue("记录");
    await page.find(".record-editor").trigger("submit");
    await flushPromises();
    await page
      .findAll("button")
      .find((b) => b.text() === "撤销上一步")!
      .trigger("click");
    await flushPromises();
    expect(page.get("[role=alert]").text()).toBe("记录已被后续修改");
    expect(page.text()).not.toContain("已撤销上一步");
    expect(fetcher).toHaveBeenCalledTimes(4);
    page.unmount();
  });
  it("hides the old skill actions while selecting a different rule", async () => {
    const one = {
      name: "one",
      description: "第一条",
      enabled: true,
      version: "0.1.0",
      body: "one",
    };
    const two = { ...one, name: "two", description: "第二条" };
    let finish!: (value: Response) => void;
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json({ skills: [one, two] }))
      .mockResolvedValueOnce(json(one))
      .mockResolvedValueOnce(json({ versions: [] }))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((r) => {
            finish = r;
          }),
      )
      .mockResolvedValueOnce(json({ versions: [] }));
    vi.stubGlobal("fetch", fetcher);
    const page = mount(SkillsPage);
    await flushPromises();
    await page.findAll(".skill-item")[0]!.trigger("click");
    await flushPromises();
    expect(page.text()).toContain("编辑规则");
    await page.findAll(".skill-item")[1]!.trigger("click");
    expect(page.text()).not.toContain("编辑规则");
    finish(json(two));
    await flushPromises();
    expect(page.find(".skill-detail h2").text()).toBe("two");
    page.unmount();
  });
  it("clears secret input after a failed request and keeps other settings", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          json({
            model: "test",
            api_base: "https://example.com",
            thinking: false,
            max_turns: 7,
            configured: false,
            api_key_hint: "",
          }),
        )
        .mockRejectedValueOnce(new Error("network lost")),
    );
    const page = mount(ModelSettingsPage);
    await flushPromises();
    await page.find("input[type=password]").setValue("secret-value");
    await page.find("form").trigger("submit");
    await flushPromises();
    expect(
      (page.get("input[type=password]").element as HTMLInputElement).value,
    ).toBe("");
    expect(page.get("[role=alert]").text()).toBe("network lost");
    expect((page.findAll("input")[0]!.element as HTMLInputElement).value).toBe(
      "test",
    );
    page.unmount();
  });
});
