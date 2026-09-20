/**
 * Nous Theme — light/dark mode with CSS custom properties.
 *
 * Provides ThemeProvider + useTheme hook. All design tokens are
 * injected as CSS custom properties on :root so every component
 * can reference var(--nous-*) without prop threading.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";


// Types


export type ThemeMode = "light" | "dark" | "system";

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: "system",
  resolved: "light",
  setMode: () => {},
  toggle: () => {},
});


// Token definitions


const lightTokens: Record<string, string> = {
  "--nous-bg": "#F9F8F6",
  "--nous-surface": "#FFFFFF",
  "--nous-surface-hover": "#F5F3F0",
  "--nous-surface-active": "#EFECE8",
  "--nous-elevated": "#FFFFFF",

  "--nous-text": "#1A1D23",
  "--nous-text-secondary": "#6B6F78",
  "--nous-text-tertiary": "#9CA0A8",
  "--nous-text-inverse": "#FFFFFF",

  "--nous-border": "#E8E5E0",
  "--nous-border-light": "#F0EDE8",
  "--nous-border-focus": "#C4BDB4",

  "--nous-accent": "#0D7B6E",
  "--nous-accent-hover": "#0A6559",
  "--nous-accent-soft": "#E6F4F2",
  "--nous-accent-muted": "#DCEFEC",

  "--nous-success": "#1D8A5E",
  "--nous-success-soft": "#E8F5EF",
  "--nous-warning": "#C4701E",
  "--nous-warning-soft": "#FDF3E6",
  "--nous-danger": "#C0393B",
  "--nous-danger-soft": "#FBECEC",
  "--nous-info": "#3B7CC0",
  "--nous-info-soft": "#ECF3FA",

  "--nous-purple": "#6B4E9B",
  "--nous-purple-soft": "#F3EFF9",
  "--nous-teal": "#0D7B6E",
  "--nous-teal-soft": "#E6F4F2",

  "--nous-shadow-sm": "0 1px 2px rgba(0,0,0,0.04)",
  "--nous-shadow-md": "0 2px 8px rgba(0,0,0,0.06)",
  "--nous-shadow-lg": "0 4px 16px rgba(0,0,0,0.08)",
  "--nous-shadow-xl": "0 8px 32px rgba(0,0,0,0.10)",
  "--nous-shadow-card": "0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.06)",
  "--nous-shadow-drawer": "0 8px 32px rgba(0,0,0,0.10)",

  "--nous-code-bg": "#F4F3F0",
  "--nous-code-text": "#1A1D23",
  "--nous-inline-code-bg": "#F0EDE8",
};

const darkTokens: Record<string, string> = {
  "--nous-bg": "#141519",
  "--nous-surface": "#1C1E23",
  "--nous-surface-hover": "#24262C",
  "--nous-surface-active": "#2C2E35",
  "--nous-elevated": "#24262C",

  "--nous-text": "#E8E6E3",
  "--nous-text-secondary": "#9DA0A8",
  "--nous-text-tertiary": "#6B6F78",
  "--nous-text-inverse": "#1A1D23",

  "--nous-border": "#2E3038",
  "--nous-border-light": "#25272E",
  "--nous-border-focus": "#4A4E58",

  "--nous-accent": "#4DB5A8",
  "--nous-accent-hover": "#5FC4B7",
  "--nous-accent-soft": "#142420",
  "--nous-accent-muted": "#1A302C",

  "--nous-success": "#3DBA7A",
  "--nous-success-soft": "#14261C",
  "--nous-warning": "#E09B3A",
  "--nous-warning-soft": "#2B2010",
  "--nous-danger": "#E0555A",
  "--nous-danger-soft": "#2B1518",
  "--nous-info": "#5B9BD5",
  "--nous-info-soft": "#151F2B",

  "--nous-purple": "#9B7EC4",
  "--nous-purple-soft": "#1F172B",
  "--nous-teal": "#4DB5A8",
  "--nous-teal-soft": "#142420",

  "--nous-shadow-sm": "0 1px 2px rgba(0,0,0,0.20)",
  "--nous-shadow-md": "0 2px 8px rgba(0,0,0,0.30)",
  "--nous-shadow-lg": "0 4px 16px rgba(0,0,0,0.40)",
  "--nous-shadow-xl": "0 8px 32px rgba(0,0,0,0.50)",
  "--nous-shadow-card": "0 1px 2px rgba(0,0,0,0.20), 0 2px 8px rgba(0,0,0,0.30)",
  "--nous-shadow-drawer": "0 8px 32px rgba(0,0,0,0.50)",

  "--nous-code-bg": "#1E2028",
  "--nous-code-text": "#E8E6E3",
  "--nous-inline-code-bg": "#2C2E35",
};


// Storage key


const STORAGE_KEY = "nous_theme_mode";


// Helpers


function getSystemPreference(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveTheme(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") return getSystemPreference();
  return mode;
}

function injectTokens(tokens: Record<string, string>): void {
  const root = document.documentElement;
  for (const [key, value] of Object.entries(tokens)) {
    root.style.setProperty(key, value);
  }
}


// Provider


export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") return "system";
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
    return "system";
  });

  const resolved = resolveTheme(mode);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    localStorage.setItem(STORAGE_KEY, m);
  }, []);

  const toggle = useCallback(() => {
    setMode(resolved === "light" ? "dark" : "light");
  }, [resolved, setMode]);

  // Inject CSS custom properties on change
  useEffect(() => {
    const tokens = resolved === "dark" ? darkTokens : lightTokens;
    injectTokens(tokens);
  }, [resolved]);

  // Listen for system preference changes when in "system" mode
  useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const tokens = mq.matches ? darkTokens : lightTokens;
      injectTokens(tokens);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [mode]);

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}


// Hook


export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}


// CSS-resolved color helper (for JS style objects)


/**
 * Returns a CSS variable reference string for use in inline styles.
 * Usage: style={{ color: theme("text") }}
 * Falls back to light-mode values for SSR.
 */
export function themeVar(name: string): string {
  return `var(--nous-${name})`;
}

/** All design tokens as var() references for inline style objects */
export const theme = {
  bg: themeVar("bg"),
  surface: themeVar("surface"),
  surfaceHover: themeVar("surface-hover"),
  surfaceActive: themeVar("surface-active"),
  elevated: themeVar("elevated"),
  text: themeVar("text"),
  textSecondary: themeVar("text-secondary"),
  textTertiary: themeVar("text-tertiary"),
  textInverse: themeVar("text-inverse"),
  border: themeVar("border"),
  borderLight: themeVar("border-light"),
  borderFocus: themeVar("border-focus"),
  accent: themeVar("accent"),
  accentHover: themeVar("accent-hover"),
  accentSoft: themeVar("accent-soft"),
  accentMuted: themeVar("accent-muted"),
  success: themeVar("success"),
  successSoft: themeVar("success-soft"),
  warning: themeVar("warning"),
  warningSoft: themeVar("warning-soft"),
  danger: themeVar("danger"),
  dangerSoft: themeVar("danger-soft"),
  info: themeVar("info"),
  infoSoft: themeVar("info-soft"),
  purple: themeVar("purple"),
  purpleSoft: themeVar("purple-soft"),
  teal: themeVar("teal"),
  tealSoft: themeVar("teal-soft"),
  shadowSm: themeVar("shadow-sm"),
  shadowMd: themeVar("shadow-md"),
  shadowLg: themeVar("shadow-lg"),
  shadowXl: themeVar("shadow-xl"),
  shadowCard: themeVar("shadow-card"),
  shadowDrawer: themeVar("shadow-drawer"),
  codeBg: themeVar("code-bg"),
  codeText: themeVar("code-text"),
  inlineCodeBg: themeVar("inline-code-bg"),
} as const;
