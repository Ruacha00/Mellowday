import type { AppRoute, ProductArea } from "./routeState";

export interface ProductDestination {
  area: ProductArea;
  hash: string;
  icon: string;
  label: string;
}

export interface SecondaryDestination {
  description: string;
  hash: string;
  label: string;
}

export interface PageDetails {
  description: string;
  kicker: string;
  note: string;
  title: string;
}

export const primaryDestinations: ProductDestination[] = [
  { area: "conversation", hash: "#/conversation", icon: "◯", label: "对话" },
  { area: "today", hash: "#/today", icon: "▦", label: "今日" },
  { area: "life", hash: "#/life/tasks", icon: "♧", label: "生活" },
  { area: "memory", hash: "#/memory", icon: "◇", label: "记忆" },
  { area: "settings", hash: "#/settings/appearance", icon: "✥", label: "设置" },
];

export const lifeDestinations: SecondaryDestination[] = [
  { hash: "#/life/tasks", label: "任务", description: "查看准备完成的事项与截止时间。" },
  { hash: "#/life/reminders", label: "提醒", description: "查看已经安排的通知时间。" },
  { hash: "#/life/calendar", label: "日历", description: "查看有明确开始与结束时间的安排。" },
  { hash: "#/life/notes", label: "笔记", description: "查看主动保存的自由文本。" },
];

export const settingsDestinations: SecondaryDestination[] = [
  { hash: "#/settings/appearance", label: "外观", description: "调整当前客户端的主题与显示偏好。" },
  { hash: "#/settings/persona", label: "人格设定", description: "管理助手的身份、表达方式与聊天边界。" },
  { hash: "#/settings/proactive-chat", label: "主动聊天", description: "查看安静时段、冷却与每日上限。" },
  { hash: "#/settings/providers", label: "模型提供方", description: "查看本地配置的可替换推理提供方。" },
  { hash: "#/settings/capabilities", label: "能力", description: "查看当前可用的工具与技能。" },
  { hash: "#/settings/history", label: "对话历史", description: "中性地检查已保留的会话。" },
  { hash: "#/settings/audit", label: "操作记录", description: "查看动作、确认与撤销信息。" },
  { hash: "#/settings/diagnostics", label: "诊断", description: "查看本地运行状态与故障信息。" },
];

export function pageDetails(route: AppRoute): PageDetails {
  if (route.area === "conversation") {
    return {
      kicker: "下午好",
      title: "我在这里，陪你梳理今天。",
      note: "对话是日常归处，其他区域也始终有稳定的位置。",
      description: "",
    };
  }
  if (route.area === "today") {
    return {
      kicker: "今日",
      title: "今天",
      note: "从当前生活记录派生的一日概览。",
      description: "每日回顾只派生视图；源生活记录仍是事实来源。",
    };
  }
  if (route.area === "memory") {
    return {
      kicker: "记忆",
      title: "记忆管理",
      note: "中性地查看与管理值得长期保留的信息。",
      description: "记忆独立于对话历史和生活记录。",
    };
  }
  const destinations = route.area === "life"
    ? lifeDestinations
    : settingsDestinations;
  const destination = destinations.find((item) => item.hash === route.hash)
    ?? destinations[0];
  return {
    kicker: route.area === "life" ? "生活" : "设置",
    title: destination.label,
    note: route.area === "life"
      ? "每类生活记录都保留自己的结构与事实来源。"
      : "管理界面保持中性、准确，不使用人格化表达。",
    description: destination.description,
  };
}

export function placeholderCards(route: AppRoute): Array<[string, string]> {
  if (route.area === "today") {
    return [
      ["接下来", "17:30 · 给家里打电话"],
      ["今天的任务", "项目说明 · 继续整理"],
      ["给自己留白", "晚间散步 · 不设提醒"],
    ];
  }
  if (route.area === "memory") {
    return [
      ["偏好", "不喜欢把随口聊天自动转成任务"],
      ["重要事项", "正在整理新版应用结构说明"],
      ["管理边界", "记忆与生活记录分开保存"],
    ];
  }
  return [
    ["当前页面", pageDetails(route).title],
    ["状态", "可信的只读内容占位"],
    ["验证重点", "路由、焦点、溢出与返回"],
  ];
}
