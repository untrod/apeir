/**
 * Nous Design System — Chat-first, off-white, premium, minimal.
 *
 * All color values are CSS custom properties (var(--nous-*)) so they
 * respond to ThemeProvider light/dark mode switching.
 *
 * Usage:
 *   import { colors, typo, radius, shadow, space, card, input, btn, fadeIn } from "./design";
 *   <div style={{ ...card, background: colors.surface }}>
 */

import type React from "react";


// Colors — all via CSS custom properties for theming


export const colors = {
  // Surfaces
  bg: "var(--nous-bg)",
  surface: "var(--nous-surface)",
  surfaceHover: "var(--nous-surface-hover)",
  surfaceActive: "var(--nous-surface-active)",
  elevated: "var(--nous-elevated)",

  // Text
  text: "var(--nous-text)",
  textSecondary: "var(--nous-text-secondary)",
  textTertiary: "var(--nous-text-tertiary)",
  textInverse: "var(--nous-text-inverse)",

  // Borders
  border: "var(--nous-border)",
  borderLight: "var(--nous-border-light)",
  borderFocus: "var(--nous-border-focus)",

  // Accent — warm teal-green, premium and calm
  accent: "var(--nous-accent)",
  accentHover: "var(--nous-accent-hover)",
  accentSoft: "var(--nous-accent-soft)",
  accentMuted: "var(--nous-accent-muted)",

  // Status
  success: "var(--nous-success)",
  successSoft: "var(--nous-success-soft)",
  warning: "var(--nous-warning)",
  warningSoft: "var(--nous-warning-soft)",
  danger: "var(--nous-danger)",
  dangerSoft: "var(--nous-danger-soft)",
  info: "var(--nous-info)",
  infoSoft: "var(--nous-info-soft)",

  // Special
  purple: "var(--nous-purple)",
  purpleSoft: "var(--nous-purple-soft)",
  teal: "var(--nous-teal)",
  tealSoft: "var(--nous-teal-soft)",

  // Code
  codeBg: "var(--nous-code-bg)",
  codeText: "var(--nous-code-text)",
  inlineCodeBg: "var(--nous-inline-code-bg)",

  // Shadows (applied via shadow tokens)
  shadowSm: "var(--nous-shadow-sm)",
  shadowMd: "var(--nous-shadow-md)",
  shadowLg: "var(--nous-shadow-lg)",
  shadowXl: "var(--nous-shadow-xl)",
} as const;


// Typography


export const typo = {
  font: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  mono: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",

  // Sizes
  xs: "11px",
  sm: "12px",
  base: "14px",
  md: "16px",
  lg: "18px",
  xl: "22px",
  xxl: "28px",

  // Weights
  normal: 400 as const,
  medium: 500 as const,
  semibold: 600 as const,
  bold: 700 as const,

  // Line heights
  tight: "1.25",
  body: "1.5",
  relaxed: "1.7",
} as const;


// Radii — consistently rounded


export const radius = {
  sm: "6px",
  md: "10px",
  lg: "14px",
  xl: "18px",
  full: "9999px",
} as const;


// Shadows


export const shadow = {
  sm: "var(--nous-shadow-sm)",
  md: "var(--nous-shadow-md)",
  lg: "var(--nous-shadow-lg)",
  xl: "var(--nous-shadow-xl)",
  card: "var(--nous-shadow-card)",
  drawer: "var(--nous-shadow-drawer)",
  input: `0 0 0 2px ${colors.accentSoft}`,
} as const;


// Spacing scale (4px base)


export const space = {
  xs: "4px",
  sm: "8px",
  md: "12px",
  lg: "16px",
  xl: "24px",
  xxl: "32px",
  xxxl: "48px",
} as const;


// Pre-built component styles (React.CSSProperties)


export const card: React.CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: radius.lg,
  padding: space.xl,
  boxShadow: shadow.card,
};

export const cardSubtle: React.CSSProperties = {
  ...card,
  boxShadow: "none",
  background: colors.bg,
};

export const input: React.CSSProperties = {
  width: "100%",
  border: `1px solid ${colors.border}`,
  borderRadius: radius.md,
  padding: `${space.md} ${space.lg}`,
  fontSize: typo.base,
  fontFamily: typo.font,
  color: colors.text,
  background: colors.surface,
  outline: "none",
  transition: "border-color 0.15s, box-shadow 0.15s",
};

export const btn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: space.sm,
  padding: `${space.sm} ${space.lg}`,
  fontSize: typo.base,
  fontWeight: typo.medium,
  fontFamily: typo.font,
  border: "none",
  borderRadius: radius.md,
  cursor: "pointer",
  transition: "background 0.15s, transform 0.1s",
  userSelect: "none",
};

export const btnPrimary: React.CSSProperties = {
  ...btn,
  background: colors.accent,
  color: colors.textInverse,
};

export const btnSecondary: React.CSSProperties = {
  ...btn,
  background: colors.surface,
  color: colors.text,
  border: `1px solid ${colors.border}`,
};

export const badge: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: `2px ${space.sm}`,
  fontSize: typo.xs,
  fontWeight: typo.medium,
  borderRadius: radius.full,
};


// Animation keyframes (as style objects)


export const fadeIn: React.CSSProperties = {
  animation: "nousFadeIn 0.2s ease-out",
};

export const slideUp: React.CSSProperties = {
  animation: "nousSlideUp 0.25s ease-out",
};

export const slideInRight: React.CSSProperties = {
  animation: "nousSlideInRight 0.3s ease-out",
};

// Inject keyframes once + base body styles
export function injectDesignTokens(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById("nous-design-tokens")) return;
  const style = document.createElement("style");
  style.id = "nous-design-tokens";
  style.textContent = `
    @keyframes nousFadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes nousSlideUp {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes nousSlideInRight {
      from { opacity: 0; transform: translateX(16px); }
      to { opacity: 1; transform: translateX(0); }
    }
    @keyframes nousPulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }
    @keyframes nousSpin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    @keyframes nousProgress {
      from { width: 0%; }
    }
    @keyframes nousShimmer {
      0% { background-position: -200% 0; }
      100% { background-position: 200% 0; }
    }
    @keyframes nousToastIn {
      from { opacity: 0; transform: translateY(-8px) scale(0.96); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: ${typo.font};
      font-size: ${typo.base};
      color: ${colors.text};
      background: ${colors.bg};
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      transition: background 0.2s ease, color 0.2s ease;
    }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: ${colors.border}; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: ${colors.textTertiary}; }
  `;
  document.head.appendChild(style);
}


// Status color mapping


export function statusColor(status: string): { bg: string; text: string; dot: string } {
  const s = status.toLowerCase();
  if (s === "completed" || s === "success" || s === "passed" || s === "online" || s === "approved")
    return { bg: colors.successSoft, text: colors.success, dot: colors.success };
  if (s === "failed" || s === "error" || s === "offline" || s === "denied" || s === "rejected")
    return { bg: colors.dangerSoft, text: colors.danger, dot: colors.danger };
  if (s === "running" || s === "in_progress" || s === "active" || s === "dispatching")
    return { bg: colors.accentSoft, text: colors.accent, dot: colors.accent };
  if (s === "pending" || s === "awaiting_approval" || s === "queued" || s === "planning")
    return { bg: colors.warningSoft, text: colors.warning, dot: colors.warning };
  if (s === "cancelled" || s === "paused" || s === "expired")
    return { bg: "var(--nous-border-light)", text: colors.textTertiary, dot: colors.textTertiary };
  if (s === "verifying")
    return { bg: colors.purpleSoft, text: colors.purple, dot: colors.purple };
  return { bg: colors.infoSoft, text: colors.info, dot: colors.info };
}
