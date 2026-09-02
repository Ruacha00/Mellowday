export type ProductArea =
  | "conversation"
  | "today"
  | "life"
  | "memory"
  | "settings";

export interface AppRoute {
  area: ProductArea;
  hash: string;
  path: string;
}

const canonicalAreas = new Map<string, ProductArea>([
  ["/conversation", "conversation"],
  ["/today", "today"],
  ["/memory", "memory"],
  ["/life/tasks", "life"],
  ["/life/reminders", "life"],
  ["/life/calendar", "life"],
  ["/life/notes", "life"],
  ["/settings/appearance", "settings"],
  ["/settings/persona", "settings"],
  ["/settings/proactive-chat", "settings"],
  ["/settings/providers", "settings"],
  ["/settings/capabilities", "settings"],
  ["/settings/history", "settings"],
  ["/settings/audit", "settings"],
  ["/settings/diagnostics", "settings"],
]);

export function canonicalizeHash(rawHash: string): AppRoute {
  const requestedPath = rawHash.replace(/^#/, "") || "/conversation";
  const path =
    requestedPath === "/life"
      ? "/life/tasks"
      : requestedPath === "/settings"
        ? "/settings/appearance"
        : canonicalAreas.has(requestedPath)
          ? requestedPath
          : "/conversation";

  return {
    area: canonicalAreas.get(path) ?? "conversation",
    hash: `#${path}`,
    path,
  };
}
