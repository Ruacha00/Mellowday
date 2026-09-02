import { describe, expect, it } from "vitest";

import type { ConversationSummary } from "../services/conversationApi";
import {
  recentConversationSummaries,
  recentConversationTitle,
  resolveActiveConversationId,
} from "./recentConversations";

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

  it("prefers a stored title and otherwise uses normalized stored content", () => {
    const untitled = {
      ...summary(Date.UTC(2026, 8, 2) / 1_000),
      preview: "  Plan   the launch\nnext week  ",
    };

    expect(recentConversationTitle({
      ...untitled,
      title: "  Launch notes  ",
    })).toBe("Launch notes");
    expect(recentConversationTitle(untitled)).toBe("Plan the launch next week");
  });
});

describe("recent conversation ordering", () => {
  it("keeps the 20 most recently active conversations in descending order", () => {
    const summaries = Array.from({ length: 23 }, (_, index) => ({
      ...summary(index + 1),
      conversationId: `conversation-${index + 1}`,
    }));

    const recent = recentConversationSummaries(summaries);

    expect(recent).toHaveLength(20);
    expect(recent.map((item) => item.conversationId)).toEqual(
      Array.from(
        { length: 20 },
        (_, index) => `conversation-${23 - index}`,
      ),
    );
  });

  it("keeps the selected conversation when it falls outside the recent 20", () => {
    const summaries = Array.from({ length: 23 }, (_, index) => ({
      ...summary(index + 1),
      conversationId: `conversation-${index + 1}`,
    }));

    expect(resolveActiveConversationId(summaries, "conversation-1")).toBe(
      "conversation-1",
    );
    expect(resolveActiveConversationId(summaries, "missing")).toBe(
      "conversation-23",
    );
  });
});
