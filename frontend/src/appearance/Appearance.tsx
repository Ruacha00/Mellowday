import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PropsWithChildren,
} from "react";

import {
  MINIMAL_DEFAULTS,
  isFixedTheme,
  loadAppearance,
  saveAppearance,
  themeDefinitions,
  tokensForAppearance,
  type AppearancePreferences,
  type MinimalSettings,
  type ThemeId,
  type ThemeTokens,
} from "./appearanceState";

interface AppearanceContextValue {
  appearance: AppearancePreferences;
  resetMinimal: () => void;
  selectTheme: (theme: ThemeId) => void;
  updateMinimal: (change: Partial<MinimalSettings>) => void;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function AppearanceProvider({ children }: PropsWithChildren) {
  const [storage] = useState(resolveStorage);
  const [appearance, setAppearance] = useState(() => loadAppearance(storage));

  const commit = useCallback((next: AppearancePreferences) => {
    setAppearance(next);
    saveAppearance(storage, next);
  }, [storage]);
  const selectTheme = useCallback((theme: ThemeId) => {
    commit({ ...appearance, theme });
  }, [appearance, commit]);
  const updateMinimal = useCallback((change: Partial<MinimalSettings>) => {
    commit({
      ...appearance,
      theme: "minimal",
      minimal: { ...appearance.minimal, ...change },
    });
  }, [appearance, commit]);
  const resetMinimal = useCallback(() => {
    commit({
      ...appearance,
      theme: "minimal",
      minimal: { ...MINIMAL_DEFAULTS },
    });
  }, [appearance, commit]);

  useLayoutEffect(() => {
    const root = document.documentElement;
    const tokens = tokensForAppearance(appearance);
    root.dataset.theme = appearance.theme;
    for (const [token, property] of Object.entries(TOKEN_PROPERTIES)) {
      root.style.setProperty(property, tokens[token as keyof ThemeTokens]);
    }
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    themeColor?.setAttribute("content", tokens.background);
  }, [appearance]);

  const value = useMemo<AppearanceContextValue>(() => ({
    appearance,
    resetMinimal,
    selectTheme,
    updateMinimal,
  }), [appearance, resetMinimal, selectTheme, updateMinimal]);

  return (
    <AppearanceContext.Provider value={value}>
      {children}
    </AppearanceContext.Provider>
  );
}

export function AppearanceControls() {
  const { appearance, resetMinimal, selectTheme, updateMinimal } = useAppearance();
  const themes = Object.keys(themeDefinitions) as ThemeId[];

  const onThemeKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % themes.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + themes.length) % themes.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = themes.length - 1;
    }
    if (nextIndex === null) {
      return;
    }
    event.preventDefault();
    const options = event.currentTarget.parentElement
      ?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
    selectTheme(themes[nextIndex]);
    options?.[nextIndex]?.focus();
  };

  return (
    <section aria-label="外观设置" className="appearance-controls">
      <div aria-label="主题" className="theme-options" role="radiogroup">
        {themes.map((theme, index) => {
          const definition = themeDefinitions[theme];
          return (
            <button
              aria-checked={appearance.theme === theme}
              className="theme-option"
              key={theme}
              onClick={() => selectTheme(theme)}
              onKeyDown={(event) => onThemeKeyDown(event, index)}
              role="radio"
              tabIndex={appearance.theme === theme ? 0 : -1}
              type="button"
            >
              <span aria-hidden="true" className={`theme-swatch theme-swatch-${theme}`} />
              <span>{definition.label}</span>
              <small>{definition.kind === "fixed" ? "固定配色" : "可调浅色"}</small>
            </button>
          );
        })}
      </div>
      {appearance.theme === "minimal" ? (
        <div className="minimal-controls">
          <label>
            <span>强调色色相</span>
            <output>{appearance.minimal.accentHue}°</output>
            <input
              aria-label="强调色色相"
              max="359"
              min="0"
              onChange={(event) => updateMinimal({ accentHue: Number(event.currentTarget.value) })}
              type="range"
              value={appearance.minimal.accentHue}
            />
          </label>
          <label>
            <span>背景亮度</span>
            <output>{appearance.minimal.backgroundLightness}%</output>
            <input
              aria-label="背景亮度"
              max="100"
              min="88"
              onChange={(event) => updateMinimal({ backgroundLightness: Number(event.currentTarget.value) })}
              type="range"
              value={appearance.minimal.backgroundLightness}
            />
          </label>
          <button className="minimal-reset" onClick={resetMinimal} type="button">
            重置简约外观
          </button>
        </div>
      ) : (
        <p className="fixed-theme-note">固定主题配色与装饰不可编辑。</p>
      )}
    </section>
  );
}

export function ThemeDecoration() {
  const { appearance } = useAppearance();
  if (!isFixedTheme(appearance.theme)) {
    return null;
  }
  const assets = themeDefinitions[appearance.theme].assets;
  return (
    <div aria-hidden="true" className="theme-decoration" data-theme-decoration>
      <img alt="" className="theme-decoration-emblem" decoding="async" src={assets.emblem} />
      <img alt="" className="theme-decoration-corner" decoding="async" src={assets.corner} />
      <img alt="" className="theme-decoration-motif" decoding="async" src={assets.motif} />
    </div>
  );
}

function useAppearance(): AppearanceContextValue {
  const value = useContext(AppearanceContext);
  if (value === null) {
    throw new Error("Appearance components require AppearanceProvider");
  }
  return value;
}

const TOKEN_PROPERTIES: Record<keyof ThemeTokens, string> = {
  background: "--bg",
  surface: "--surface",
  surfaceStrong: "--surface-strong",
  ink: "--ink",
  inkMuted: "--ink-muted",
  accent: "--accent",
  accentStrong: "--accent-strong",
  onAccent: "--on-accent",
  border: "--border",
  focus: "--focus",
  control: "--control",
};

function resolveStorage(): Pick<Storage, "getItem" | "setItem"> {
  try {
    return window.localStorage;
  } catch {
    return {
      getItem: () => null,
      setItem: () => undefined,
    };
  }
}
