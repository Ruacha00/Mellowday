import type { ConversationSummary } from "../services/conversationApi";

export function recentConversationTitle(
  summary: ConversationSummary,
): string {
  const activity = new Date(summary.updatedAt * 1_000);
  if (!Number.isFinite(activity.valueOf())) {
    return "未命名对话";
  }
  return `${activity.getUTCFullYear()}年${activity.getUTCMonth() + 1}月${activity.getUTCDate()}日的对话`;
}
