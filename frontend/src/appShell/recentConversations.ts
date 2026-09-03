import type { ConversationSummary } from "../services/conversationApi";

const RECENT_CONVERSATION_LIMIT = 20;
const CONTENT_TITLE_LIMIT = 42;

export function recentConversationSummaries(
  summaries: ConversationSummary[],
): ConversationSummary[] {
  return [...summaries]
    .sort((left, right) => {
      const activityDifference = right.updatedAt - left.updatedAt;
      return activityDifference === 0
        ? left.conversationId.localeCompare(right.conversationId)
        : activityDifference;
    })
    .slice(0, RECENT_CONVERSATION_LIMIT);
}

export function resolveActiveConversationId(
  summaries: ConversationSummary[],
  activeConversationId: string,
): string {
  return summaries.some(
    (summary) => summary.conversationId === activeConversationId,
  )
    ? activeConversationId
    : recentConversationSummaries(summaries)[0]?.conversationId ??
        activeConversationId;
}

export function recentConversationTitle(
  summary: ConversationSummary,
): string {
  const storedTitle = normalizedTitle(summary.title);
  if (storedTitle !== null) {
    return storedTitle;
  }
  const contentTitle = normalizedTitle(summary.preview);
  if (contentTitle !== null) {
    const characters = [...contentTitle];
    return characters.length <= CONTENT_TITLE_LIMIT
      ? contentTitle
      : `${characters.slice(0, CONTENT_TITLE_LIMIT).join("")}…`;
  }
  const activity = new Date(summary.updatedAt * 1_000);
  if (summary.updatedAt <= 0 || !Number.isFinite(activity.valueOf())) {
    return "未命名对话";
  }
  return `${activity.getUTCFullYear()}年${activity.getUTCMonth() + 1}月${activity.getUTCDate()}日的对话`;
}

function normalizedTitle(value: string | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  const normalized = value.replace(/\s+/gu, " ").trim();
  return normalized.length === 0 ? null : normalized;
}
