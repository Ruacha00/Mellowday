import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AuditService } from "../services/auditApi";
import type { ConversationService } from "../services/conversationApi";
import { ConversationHistoryPage } from "./ConversationHistoryPage";
import { OperationRecordsPage } from "./OperationRecordsPage";

const conversationService: ConversationService = {
  listConversations: vi.fn(),
  loadConversation: vi.fn(),
  renameConversation: vi.fn(),
  sendMessage: vi.fn(),
  listPendingConfirmations: vi.fn(),
  decideConfirmation: vi.fn(),
  requestResetConfirmation: vi.fn(),
  decideReset: vi.fn(),
};

const auditService: AuditService = { listRecords: vi.fn() };

describe("Settings history and operation-record pages", () => {
  it("uses neutral route-owned loading copy and keeps the concepts separate", () => {
    const markup = renderToStaticMarkup(
      <>
        <ConversationHistoryPage onHistoryChanged={vi.fn()} service={conversationService} />
        <OperationRecordsPage service={auditService} />
      </>,
    );

    expect(markup).toContain("正在加载对话历史");
    expect(markup).toContain("正在加载操作记录");
    expect(markup).toContain("不属于记忆");
    expect(markup).toContain("不会补写工具内部过程");
    expect(markup).not.toMatch(/亲爱的|宝贝|陪你聊聊/u);
  });
});
