import { describe, expect, it } from "vitest";

import {
  loadWideNavigation,
  saveWideNavigation,
  toggleWideNavigation,
} from "./wideNavigationState";

function memoryStorage(initialValue: string | null = null) {
  let value = initialValue;
  return {
    getItem: () => value,
    setItem: (_key: string, nextValue: string) => {
      value = nextValue;
    },
    value: () => value,
  };
}

describe("wide navigation preference", () => {
  it("defaults to the labeled rail", () => {
    expect(loadWideNavigation(memoryStorage())).toBe("rail");
  });

  it("persists and restores the explicit dock state", () => {
    const storage = memoryStorage();

    saveWideNavigation(storage, "dock");

    expect(loadWideNavigation(storage)).toBe("dock");
    expect(storage.value()).toBe(
      JSON.stringify({ version: 1, wideNavigation: "dock" }),
    );
  });

  it("repairs invalid stored preferences to the rail default", () => {
    expect(loadWideNavigation(memoryStorage('{"wideNavigation":"tiny"}')))
      .toBe("rail");
  });

  it("changes only when the user explicitly toggles the wide state", () => {
    expect(toggleWideNavigation("rail")).toBe("dock");
    expect(toggleWideNavigation("dock")).toBe("rail");
  });
});
