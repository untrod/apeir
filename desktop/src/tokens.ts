/**
 * Nous Control Center — Design Tokens
 *
 * All visual design constants. No hardcoded colors in components.
 * Light theme is the default; dark theme tokens mirror this structure.
 *
 * Usage in components:
 *   import { tokens } from '@/design';
 *   <div style={{ background: tokens.color.surface.primary }}>...</div>
 *
 * CSS variables are injected via ThemeProvider into :root.
 */

// Color palette

const lightColors = {
  // Surface
  surface: {
    primary: 'var(--nous-surface-primary, #FFFFFF)',
    secondary: 'var(--nous-surface-secondary, #F8F9FA)',
    tertiary: 'var(--nous-surface-tertiary, #F0F1F3)',
    elevated: 'var(--nous-surface-elevated, #FFFFFF)',
    inverse: 'var(--nous-surface-inverse, #1A1A2E)',
  },
  // Text
  text: {
    primary: 'var(--nous-text-primary, #1A1A2E)',
    secondary: 'var(--nous-text-secondary, #6B7280)',
    tertiary: 'var(--nous-text-tertiary, #9CA3AF)',
    inverse: 'var(--nous-text-inverse, #FFFFFF)',
    link: 'var(--nous-text-link, #3B82F6)',
    error: 'var(--nous-text-error, #EF4444)',
    success: 'var(--nous-text-success, #10B981)',
    warning: 'var(--nous-text-warning, #F59E0B)',
  },
  // Border
  border: {
    light: 'var(--nous-border-light, #E5E7EB)',
    medium: 'var(--nous-border-medium, #D1D5DB)',
    focus: 'var(--nous-border-focus, #3B82F6)',
  },
  // Brand
  brand: {
    primary: 'var(--nous-brand-primary, #3B82F6)',
    primaryHover: 'var(--nous-brand-primary-hover, #2563EB)',
    secondary: 'var(--nous-brand-secondary, #8B5CF6)',
    accent: 'var(--nous-brand-accent, #06B6D4)',
  },
  // Semantic
  semantic: {
    success: 'var(--nous-semantic-success, #10B981)',
    warning: 'var(--nous-semantic-warning, #F59E0B)',
    error: 'var(--nous-semantic-error, #EF4444)',
    info: 'var(--nous-semantic-info, #3B82F6)',
  },
  // Status
  status: {
    online: 'var(--nous-status-online, #10B981)',
    offline: 'var(--nous-status-offline, #9CA3AF)',
    degraded: 'var(--nous-status-degraded, #F59E0B)',
    running: 'var(--nous-status-running, #3B82F6)',
    completed: 'var(--nous-status-completed, #10B981)',
    failed: 'var(--nous-status-failed, #EF4444)',
    paused: 'var(--nous-status-paused, #F59E0B)',
  },
  // Scrollbar
  scrollbar: {
    thumb: 'var(--nous-scrollbar-thumb, #D1D5DB)',
    track: 'var(--nous-scrollbar-track, transparent)',
  },
};

const darkColors = {
  surface: {
    primary: '#111827',
    secondary: '#1F2937',
    tertiary: '#374151',
    elevated: '#1F2937',
    inverse: '#F9FAFB',
  },
  text: {
    primary: '#F9FAFB',
    secondary: '#9CA3AF',
    tertiary: '#6B7280',
    inverse: '#111827',
    link: '#60A5FA',
    error: '#F87171',
    success: '#34D399',
    warning: '#FBBF24',
  },
  border: {
    light: '#374151',
    medium: '#4B5563',
    focus: '#60A5FA',
  },
  brand: {
    primary: '#3B82F6',
    primaryHover: '#60A5FA',
    secondary: '#8B5CF6',
    accent: '#06B6D4',
  },
  semantic: {
    success: '#34D399',
    warning: '#FBBF24',
    error: '#F87171',
    info: '#60A5FA',
  },
  status: {
    online: '#34D399',
    offline: '#6B7280',
    degraded: '#FBBF24',
    running: '#60A5FA',
    completed: '#34D399',
    failed: '#F87171',
    paused: '#FBBF24',
  },
  scrollbar: {
    thumb: '#4B5563',
    track: 'transparent',
  },
};

// Typography

const typography = {
  fontFamily: {
    sans: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    mono: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
  },
  fontSize: {
    xs: 'var(--nous-font-xs, 0.75rem)',
    sm: 'var(--nous-font-sm, 0.8125rem)',
    base: 'var(--nous-font-base, 0.875rem)',
    lg: 'var(--nous-font-lg, 1rem)',
    xl: 'var(--nous-font-xl, 1.25rem)',
    '2xl': 'var(--nous-font-2xl, 1.5rem)',
    '3xl': 'var(--nous-font-3xl, 1.875rem)',
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  lineHeight: {
    tight: 1.25,
    normal: 1.5,
    relaxed: 1.75,
  },
};

// Spacing

const spacing = {
  px: 'var(--nous-spacing-px, 1px)',
  0: 'var(--nous-spacing-0, 0)',
  1: 'var(--nous-spacing-1, 0.25rem)',
  2: 'var(--nous-spacing-2, 0.5rem)',
  3: 'var(--nous-spacing-3, 0.75rem)',
  4: 'var(--nous-spacing-4, 1rem)',
  5: 'var(--nous-spacing-5, 1.25rem)',
  6: 'var(--nous-spacing-6, 1.5rem)',
  8: 'var(--nous-spacing-8, 2rem)',
  10: 'var(--nous-spacing-10, 2.5rem)',
  12: 'var(--nous-spacing-12, 3rem)',
  16: 'var(--nous-spacing-16, 4rem)',
};

// Borders & Radius

const radius = {
  none: 'var(--nous-radius-none, 0)',
  sm: 'var(--nous-radius-sm, 0.25rem)',
  md: 'var(--nous-radius-md, 0.5rem)',
  lg: 'var(--nous-radius-lg, 0.75rem)',
  xl: 'var(--nous-radius-xl, 1rem)',
  full: 'var(--nous-radius-full, 9999px)',
};

// Shadows

const shadow = {
  none: 'var(--nous-shadow-none, none)',
  sm: 'var(--nous-shadow-sm, 0 1px 2px rgba(0,0,0,0.05))',
  md: 'var(--nous-shadow-md, 0 4px 6px -1px rgba(0,0,0,0.1))',
  lg: 'var(--nous-shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.1))',
  xl: 'var(--nous-shadow-xl, 0 20px 25px -5px rgba(0,0,0,0.1))',
};

// Breakpoints

const breakpoints = {
  /** >= 1440px — full three-column layout */
  desktop: '@media (min-width: 1440px)',
  /** 1024–1439px — two-column with collapsible panels */
  laptop: '@media (min-width: 1024px) and (max-width: 1439px)',
  /** 768–1023px — single column, drawer panels, tablet touch */
  tablet: '@media (min-width: 768px) and (max-width: 1023px)',
  /** < 768px — minimal, mobile-first fallback (not primary target) */
  mobile: '@media (max-width: 767px)',
};

// Touch targets

const touch = {
  /** Minimum clickable area: 40px */
  minTarget: 'var(--nous-touch-min, 40px)',
};

// Z-Index

const zIndex = {
  base: 0,
  dropdown: 100,
  sticky: 200,
  drawer: 300,
  modal: 400,
  toast: 500,
  tooltip: 600,
};

// Transitions

const transition = {
  fast: 'var(--nous-transition-fast, 150ms ease)',
  normal: 'var(--nous-transition-normal, 250ms ease)',
  slow: 'var(--nous-transition-slow, 350ms ease)',
};

// Exports

export const lightTokens = {
  colors: lightColors,
};

export const darkTokens = {
  colors: darkColors,
};

export const tokens = {
  color: lightColors,
  typo: typography,
  space: spacing,
  radius,
  shadow,
  breakpoints,
  touch,
  zIndex,
  transition,
};

/** DPI scaling: 1.0 → 100%, 1.25 → 125%, 1.5 → 150%, 1.75 → 175%, 2.0 → 200% */
export type DpiScale = 1.0 | 1.25 | 1.5 | 1.75 | 2.0;

export function getDpiScale(): DpiScale {
  if (typeof window === 'undefined') return 1.0;
  const dpr = window.devicePixelRatio || 1;
  if (dpr >= 2.0) return 2.0;
  if (dpr >= 1.75) return 1.75;
  if (dpr >= 1.5) return 1.5;
  if (dpr >= 1.25) return 1.25;
  return 1.0;
}
