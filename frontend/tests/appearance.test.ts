import { describe, expect, it } from "vitest";
import {
  loadAppearance,
  tokensForAppearance,
  themeDefinitions,
} from "../src/appearance/appearanceState";
describe("appearance preferences", () => {
  it("recovers malformed storage and clamps minimal controls", () => {
    expect(loadAppearance({ getItem: () => "broken" }).theme).toBe("sky");
    const restored = loadAppearance({
      getItem: () =>
        JSON.stringify({
          version: 1,
          theme: "minimal",
          minimal: { accentHue: 999, backgroundLightness: 0 },
        }),
    });
    expect(restored.minimal).toEqual({
      accentHue: 359,
      backgroundLightness: 88,
    });
  });
  it("restores each supported theme without losing its token set", () => {
    for (const theme of Object.keys(themeDefinitions)) {
      const restored = loadAppearance({
        getItem: () => JSON.stringify({ version: 1, theme }),
      });
      expect(restored.theme).toBe(theme);
      expect(tokensForAppearance(restored).ink).toBeTruthy();
    }
  });
});
