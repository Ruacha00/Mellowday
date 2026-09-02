import { describe, expect, it } from "vitest";

import type { ConversationSummary } from "../services/conversationApi";
import { recentConversationTitle } from "./recentConversations";

function summary(updatedAt: number): ConversationSummary {
  return {
    conversationId: "internal-conversation-id",
    messageCount: 2,
    characterCount: 24,
    createdAt: updatedAt,
    updatedAt,
  };
}

describe("recent conversation titles", () => {
  it("uses a deterministic date instead of exposing an internal id", () => {
    const septemberSecond = Date.UTC(2026, 8, 2) / 1_000;

    expect(recentConversationTitle(summary(septemberSecond))).toBe(
      "2026年9月2日的对话",
    );
  });

  it("uses a neutral fallback when no usable activity date exists", () => {
    expect(recentConversationTitle(summary(Number.NaN))).toBe("未命名对话");
  });
});
