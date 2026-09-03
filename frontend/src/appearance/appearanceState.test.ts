import { describe, expect, it } from "vitest";

import {
  APPEARANCE_STORAGE_KEY,
  DEFAULT_APPEARANCE,
  FIXED_THEME_IDS,
  MINIMAL_DEFAULTS,
  deriveMinimalTokens,
  loadAppearance,
  saveAppearance,
  themeDefinitions,
} from "./appearanceState";

describe("appearance preferences", () => {
  it("uses Sky when no preference has been stored", () => {
    const storage = new MemoryStorage();

    expect(loadAppearance(storage)).toEqual(DEFAULT_APPEARANCE);
  });

  it("restores one valid versioned preference record", () => {
    const storage = new MemoryStorage({
      [APPEARANCE_STORAGE_KEY]: JSON.stringify({
        version: 1,
        theme: "minimal",
        minimal: { accentHue: 286, backgroundLightness: 91 },
      }),
    });

    expect(loadAppearance(storage)).toEqual({
      version: 1,
      theme: "minimal",
      minimal: { accentHue: 286, backgroundLightness: 91 },
    });
  });

  it("repairs invalid fields and resets unmigratable records", () => {
    const repairable = new MemoryStorage({
      [APPEARANCE_STORAGE_KEY]: JSON.stringify({
        version: 1,
        theme: "unknown",
        minimal: { accentHue: "blue", backgroundLightness: 144 },
      }),
    });
    const unmigratable = new MemoryStorage({
      [APPEARANCE_STORAGE_KEY]: JSON.stringify({
        version: 99,
        theme: "night",
        minimal: { accentHue: 80, backgroundLightness: 92 },
      }),
    });

    expect(loadAppearance(repairable)).toEqual({
      version: 1,
      theme: "sky",
      minimal: {
        accentHue: MINIMAL_DEFAULTS.accentHue,
        backgroundLightness: 100,
      },
    });
    expect(loadAppearance(unmigratable)).toEqual(DEFAULT_APPEARANCE);
  });

  it("does not let unavailable storage prevent startup or updates", () => {
    const unavailable = {
      getItem: () => {
        throw new Error("storage unavailable");
      },
      setItem: () => {
        throw new Error("storage unavailable");
      },
    } satisfies Pick<Storage, "getItem" | "setItem">;

    expect(loadAppearance(unavailable)).toEqual(DEFAULT_APPEARANCE);
    expect(() => saveAppearance(unavailable, DEFAULT_APPEARANCE)).not.toThrow();
  });
});

describe("appearance theme definitions", () => {
  it("registers four immutable fixed themes and a decoration-free Minimal theme", () => {
    expect(FIXED_THEME_IDS).toEqual(["sky", "sakura", "mint", "night"]);
    expect(Object.isFrozen(themeDefinitions)).toBe(true);

    for (const id of FIXED_THEME_IDS) {
      const definition = themeDefinitions[id];
      expect(definition.kind).toBe("fixed");
      expect(Object.isFrozen(definition.tokens)).toBe(true);
      expect(Object.keys(definition.assets)).toEqual(["emblem", "corner", "motif"]);
    }

    expect(themeDefinitions.minimal).toMatchObject({
      kind: "custom",
      assets: null,
    });
  });

  it.each(FIXED_THEME_IDS)("keeps the %s semantic token set accessible", (id) => {
    const definition = themeDefinitions[id];
    expect(contrast(definition.tokens.ink, definition.tokens.surfaceStrong))
      .toBeGreaterThanOrEqual(4.5);
    expect(contrast(definition.tokens.inkMuted, definition.tokens.surfaceStrong))
      .toBeGreaterThanOrEqual(4.5);
    expect(contrast(definition.tokens.onAccent, definition.tokens.accentStrong))
      .toBeGreaterThanOrEqual(4.5);
    expect(contrast(definition.tokens.accentStrong, definition.tokens.accent))
      .toBeGreaterThanOrEqual(4.5);
    expect(contrast(definition.tokens.focus, definition.tokens.surfaceStrong))
      .toBeGreaterThanOrEqual(3);
    expect(contrast(definition.tokens.border, definition.tokens.surfaceStrong))
      .toBeGreaterThanOrEqual(3);
    expect(contrast(definition.tokens.border, definition.tokens.surface))
      .toBeGreaterThanOrEqual(3);
  });
});

describe("Minimal semantic tokens", () => {
  it.each([88, 100])(
    "keeps text, controls, and focus contrast accessible at %s%% lightness",
    (backgroundLightness) => {
      const tokens = deriveMinimalTokens({
        accentHue: 211,
        backgroundLightness,
      });

      expect(contrast(tokens.ink, tokens.surfaceStrong)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(tokens.inkMuted, tokens.surfaceStrong)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(tokens.onAccent, tokens.accentStrong)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(tokens.focus, tokens.surfaceStrong)).toBeGreaterThanOrEqual(3);
      expect(tokens.background).toBe(`hsl(211 24% ${backgroundLightness}%)`);
    },
  );

  it.each([0, 60, 120, 180, 240, 300])(
    "keeps user-selected hue %s accessible",
    (accentHue) => {
      for (const backgroundLightness of [88, 100]) {
        const tokens = deriveMinimalTokens({ accentHue, backgroundLightness });
        expect(contrast(tokens.ink, tokens.surfaceStrong)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(tokens.inkMuted, tokens.surfaceStrong)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(tokens.onAccent, tokens.accentStrong)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(tokens.accentStrong, tokens.accent)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(tokens.focus, tokens.surfaceStrong)).toBeGreaterThanOrEqual(3);
        expect(contrast(tokens.border, tokens.surfaceStrong)).toBeGreaterThanOrEqual(3);
        expect(contrast(tokens.border, tokens.surface)).toBeGreaterThanOrEqual(3);
      }
    },
  );
});

class MemoryStorage implements Pick<Storage, "getItem" | "setItem"> {
  readonly #items = new Map<string, string>();

  constructor(initial: Record<string, string> = {}) {
    for (const [key, value] of Object.entries(initial)) {
      this.#items.set(key, value);
    }
  }

  getItem(key: string): string | null {
    return this.#items.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.#items.set(key, value);
  }
}

function contrast(left: string, right: string): number {
  const leftLuminance = luminance(parseHsl(left));
  const rightLuminance = luminance(parseHsl(right));
  return (Math.max(leftLuminance, rightLuminance) + 0.05)
    / (Math.min(leftLuminance, rightLuminance) + 0.05);
}

function parseHsl(value: string): [number, number, number] {
  const match = value.match(/^hsl\((\d+) (\d+)% (\d+)%\)$/);
  if (match === null) {
    throw new Error(`Expected an opaque HSL color, received ${value}`);
  }
  const hue = Number(match[1]) / 360;
  const saturation = Number(match[2]) / 100;
  const lightness = Number(match[3]) / 100;
  const channel = (offset: number) => {
    const position = (offset + hue) % 1;
    const factor = saturation * Math.min(lightness, 1 - lightness);
    return lightness - factor * Math.max(-1, Math.min(position * 12 - 3, 9 - position * 12, 1));
  };
  return [channel(1 / 3), channel(0), channel(2 / 3)];
}

function luminance(color: [number, number, number]): number {
  const channel = (value: number) => value <= 0.04045
    ? value / 12.92
    : ((value + 0.055) / 1.055) ** 2.4;
  return 0.2126 * channel(color[0])
    + 0.7152 * channel(color[1])
    + 0.0722 * channel(color[2]);
}
