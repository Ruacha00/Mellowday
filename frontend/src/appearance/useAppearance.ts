import { computed, reactive, watchEffect } from "vue";
import {
  loadAppearance,
  saveAppearance,
  themeDefinitions,
  tokensForAppearance,
  type ThemeId,
} from "./appearanceState";

function initial() {
  try {
    return loadAppearance(localStorage);
  } catch {
    return loadAppearance({ getItem: () => null });
  }
}
const preferences = reactive(initial());
const theme = computed(() => themeDefinitions[preferences.theme]);
const tokenNames = {
  background: "bg",
  surface: "surface",
  surfaceStrong: "surface-strong",
  ink: "ink",
  inkMuted: "ink-muted",
  accent: "accent",
  accentStrong: "accent-strong",
  onAccent: "on-accent",
  border: "border",
  focus: "focus",
  control: "control",
};
watchEffect(() => {
  const tokens = tokensForAppearance(preferences);
  for (const [key, value] of Object.entries(tokens))
    document.documentElement.style.setProperty(
      `--${tokenNames[key as keyof typeof tokenNames]}`,
      value,
    );
  document.documentElement.dataset.theme = preferences.theme;
  try {
    saveAppearance(localStorage, preferences);
  } catch {
    /* Browser storage can be disabled. */
  }
});
export function useAppearance() {
  return {
    preferences,
    theme,
    selectTheme: (id: ThemeId) => {
      preferences.theme = id;
    },
  };
}
