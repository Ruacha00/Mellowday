import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, requestJson } from "../src/api/http";

afterEach(() => vi.unstubAllGlobals());
describe("JSON API failures", () => {
  it("preserves conflict data without retrying a write", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "记录已修改", changed_fields: ["title"] }),
          { status: 409 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const result = requestJson("/api/records/undo/one", { method: "POST" });
    await expect(result).rejects.toMatchObject({
      status: 409,
      message: "记录已修改",
      data: { changed_fields: ["title"] },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("does not treat an ok:false receipt as success", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response('{"ok":false,"error":"拒绝写入"}')),
    );
    await expect(requestJson("/api/example")).rejects.toThrow("拒绝写入");
  });
  it("reports HTML fallback as an invalid API response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>app</html>")),
    );
    await expect(requestJson("/api/unknown")).rejects.toBeInstanceOf(ApiError);
  });
});
