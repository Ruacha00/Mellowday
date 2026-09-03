export type WideNavigation = "rail" | "dock";

export const WIDE_NAVIGATION_STORAGE_KEY =
  "mellowday.app-shell-preferences.v1";

interface AppShellPreferences {
  version: 1;
  wideNavigation: WideNavigation;
}

export function loadWideNavigation(
  storage: Pick<Storage, "getItem">,
): WideNavigation {
  try {
    const stored = storage.getItem(WIDE_NAVIGATION_STORAGE_KEY);
    if (stored === null) {
      return "rail";
    }
    const preferences = JSON.parse(stored) as Partial<AppShellPreferences>;
    return preferences.version === 1 &&
      (preferences.wideNavigation === "rail" ||
        preferences.wideNavigation === "dock")
      ? preferences.wideNavigation
      : "rail";
  } catch {
    return "rail";
  }
}

export function saveWideNavigation(
  storage: Pick<Storage, "setItem">,
  wideNavigation: WideNavigation,
): void {
  const preferences: AppShellPreferences = {
    version: 1,
    wideNavigation,
  };
  storage.setItem(WIDE_NAVIGATION_STORAGE_KEY, JSON.stringify(preferences));
}

export function toggleWideNavigation(
  wideNavigation: WideNavigation,
): WideNavigation {
  return wideNavigation === "rail" ? "dock" : "rail";
}
