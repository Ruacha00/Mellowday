export const APPEARANCE_STORAGE_KEY = "mellowday.appearance";

export const FIXED_THEME_IDS = ["sky", "sakura", "mint", "night"] as const;
export type FixedThemeId = (typeof FIXED_THEME_IDS)[number];
export type ThemeId = FixedThemeId | "minimal";

export interface MinimalSettings {
  accentHue: number;
  backgroundLightness: number;
}

export interface AppearancePreferences {
  version: 1;
  theme: ThemeId;
  minimal: MinimalSettings;
}

export interface ThemeTokens {
  background: string;
  surface: string;
  surfaceStrong: string;
  ink: string;
  inkMuted: string;
  accent: string;
  accentStrong: string;
  onAccent: string;
  border: string;
  focus: string;
  control: string;
}

interface FixedThemeDefinition {
  id: FixedThemeId;
  kind: "fixed";
  label: string;
  assets: Readonly<{
    emblem: string;
    corner: string;
    motif: string;
  }>;
  tokens: Readonly<ThemeTokens>;
}

interface MinimalThemeDefinition {
  id: "minimal";
  kind: "custom";
  label: string;
  assets: null;
}

export type ThemeDefinition = FixedThemeDefinition | MinimalThemeDefinition;

export const MINIMAL_DEFAULTS = Object.freeze<MinimalSettings>({
  accentHue: 211,
  backgroundLightness: 97,
});

export const DEFAULT_APPEARANCE = Object.freeze<AppearancePreferences>({
  version: 1,
  theme: "sky",
  minimal: MINIMAL_DEFAULTS,
});

const fixedTheme = (
  id: FixedThemeId,
  label: string,
  assets: FixedThemeDefinition["assets"],
  tokens: ThemeTokens,
): FixedThemeDefinition => Object.freeze({
  id,
  kind: "fixed",
  label,
  assets: Object.freeze(assets),
  tokens: Object.freeze(tokens),
});

export const themeDefinitions = Object.freeze({
  sky: fixedTheme("sky", "晴空", {
    emblem: "/static/replacement/runtime/themes/sky-emblem.webp",
    corner: "/static/replacement/runtime/themes/sky-corner.webp",
    motif: "/static/replacement/runtime/themes/sky-motif.svg",
  }, {
    background: "hsl(207 72% 94%)",
    surface: "hsl(205 64% 97%)",
    surfaceStrong: "hsl(205 60% 99%)",
    ink: "hsl(211 58% 22%)",
    inkMuted: "hsl(210 30% 36%)",
    accent: "hsl(207 70% 88%)",
    accentStrong: "hsl(210 83% 30%)",
    onAccent: "hsl(0 0% 100%)",
    border: "hsl(208 38% 48%)",
    focus: "hsl(210 100% 25%)",
    control: "hsl(207 74% 95%)",
  }),
  sakura: fixedTheme("sakura", "樱粉", {
    emblem: "/static/replacement/runtime/themes/sakura-emblem.webp",
    corner: "/static/replacement/runtime/themes/sakura-corner.webp",
    motif: "/static/replacement/runtime/themes/sakura-motif.svg",
  }, {
    background: "hsl(345 68% 95%)",
    surface: "hsl(348 58% 98%)",
    surfaceStrong: "hsl(350 60% 99%)",
    ink: "hsl(341 45% 20%)",
    inkMuted: "hsl(341 24% 35%)",
    accent: "hsl(345 70% 89%)",
    accentStrong: "hsl(343 70% 25%)",
    onAccent: "hsl(0 0% 100%)",
    border: "hsl(344 31% 47%)",
    focus: "hsl(341 86% 25%)",
    control: "hsl(348 70% 96%)",
  }),
  mint: fixedTheme("mint", "薄荷", {
    emblem: "/static/replacement/runtime/themes/mint-emblem.webp",
    corner: "/static/replacement/runtime/themes/mint-corner.webp",
    motif: "/static/replacement/runtime/themes/mint-motif.svg",
  }, {
    background: "hsl(156 42% 93%)",
    surface: "hsl(151 39% 97%)",
    surfaceStrong: "hsl(150 43% 99%)",
    ink: "hsl(165 42% 17%)",
    inkMuted: "hsl(164 25% 32%)",
    accent: "hsl(157 45% 84%)",
    accentStrong: "hsl(164 68% 23%)",
    onAccent: "hsl(0 0% 100%)",
    border: "hsl(161 27% 42%)",
    focus: "hsl(166 90% 20%)",
    control: "hsl(151 48% 94%)",
  }),
  night: fixedTheme("night", "夜色", {
    emblem: "/static/replacement/runtime/themes/night-emblem.webp",
    corner: "/static/replacement/runtime/themes/night-corner.webp",
    motif: "/static/replacement/runtime/themes/night-motif.svg",
  }, {
    background: "hsl(224 39% 11%)",
    surface: "hsl(223 34% 16%)",
    surfaceStrong: "hsl(222 30% 20%)",
    ink: "hsl(214 42% 94%)",
    inkMuted: "hsl(215 26% 75%)",
    accent: "hsl(221 48% 34%)",
    accentStrong: "hsl(215 76% 82%)",
    onAccent: "hsl(224 45% 10%)",
    border: "hsl(218 29% 55%)",
    focus: "hsl(207 100% 78%)",
    control: "hsl(221 31% 24%)",
  }),
  minimal: Object.freeze<MinimalThemeDefinition>({
    id: "minimal",
    kind: "custom",
    label: "简约",
    assets: null,
  }),
} satisfies Record<ThemeId, ThemeDefinition>);

export function loadAppearance(
  storage: Pick<Storage, "getItem">,
): AppearancePreferences {
  try {
    const stored = storage.getItem(APPEARANCE_STORAGE_KEY);
    if (stored === null) {
      return copyDefaults();
    }
    const candidate: unknown = JSON.parse(stored);
    if (!isRecord(candidate) || candidate.version !== 1) {
      return copyDefaults();
    }
    const minimal = isRecord(candidate.minimal) ? candidate.minimal : {};
    return {
      version: 1,
      theme: isThemeId(candidate.theme) ? candidate.theme : "sky",
      minimal: {
        accentHue: repairNumber(
          minimal.accentHue,
          MINIMAL_DEFAULTS.accentHue,
          0,
          359,
        ),
        backgroundLightness: repairNumber(
          minimal.backgroundLightness,
          MINIMAL_DEFAULTS.backgroundLightness,
          88,
          100,
        ),
      },
    };
  } catch {
    return copyDefaults();
  }
}

export function saveAppearance(
  storage: Pick<Storage, "setItem">,
  preferences: AppearancePreferences,
): void {
  try {
    storage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Client-local presentation state must never prevent the application starting.
  }
}

export function deriveMinimalTokens(settings: MinimalSettings): ThemeTokens {
  const hue = repairNumber(settings.accentHue, MINIMAL_DEFAULTS.accentHue, 0, 359);
  const backgroundLightness = repairNumber(
    settings.backgroundLightness,
    MINIMAL_DEFAULTS.backgroundLightness,
    88,
    100,
  );
  const surfaceLightness = Math.max(86, backgroundLightness - 2);
  return {
    background: hsl(hue, 24, backgroundLightness),
    surface: hsl(hue, 18, Math.max(87, backgroundLightness - 1)),
    surfaceStrong: hsl(hue, 16, surfaceLightness),
    ink: hsl(hue, 32, 17),
    inkMuted: hsl(hue, 18, 31),
    accent: hsl(hue, 58, 88),
    accentStrong: hsl(hue, 72, 22),
    onAccent: hsl(0, 0, 100),
    border: hsl(hue, 22, 40),
    focus: hsl(hue, 76, 22),
    control: hsl(hue, 20, Math.max(86, backgroundLightness - 3)),
  };
}

export function tokensForAppearance(
  preferences: AppearancePreferences,
): Readonly<ThemeTokens> {
  const definition = themeDefinitions[preferences.theme];
  return definition.kind === "fixed"
    ? definition.tokens
    : deriveMinimalTokens(preferences.minimal);
}

export function isFixedTheme(theme: ThemeId): theme is FixedThemeId {
  return theme !== "minimal";
}

function isThemeId(value: unknown): value is ThemeId {
  return value === "minimal" || FIXED_THEME_IDS.some((id) => id === value);
}

function repairNumber(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

function hsl(hue: number, saturation: number, lightness: number): string {
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function copyDefaults(): AppearancePreferences {
  return {
    version: 1,
    theme: "sky",
    minimal: { ...MINIMAL_DEFAULTS },
  };
}
