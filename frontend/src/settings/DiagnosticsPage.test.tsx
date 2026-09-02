import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { DiagnosticsService } from "../services/diagnosticsApi";
import { DiagnosticsPage } from "./DiagnosticsPage";

const service: DiagnosticsService = {
  getStatus: vi.fn(),
  listEvents: vi.fn(),
  listLogs: vi.fn(),
};

describe("DiagnosticsPage", () => {
  it("starts with neutral, accessible route-owned loading content", () => {
    const markup = renderToStaticMarkup(<DiagnosticsPage service={service} />);

    expect(markup).toContain("正在加载诊断数据");
    expect(markup).toContain("本地运行事实");
    expect(markup).toContain('role="status"');
    expect(markup).not.toMatch(/亲爱的|宝贝|陪你聊聊/u);
  });
});
