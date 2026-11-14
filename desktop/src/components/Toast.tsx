/**
 * Toast — non-intrusive notification system for real-time runtime events.
 *
 * Uses a lightweight pub/sub pattern so any component can fire a toast
 * without prop threading. Toasts auto-dismiss and stack at the top-right.
 */

import React, { useState, useCallback, useEffect, useRef, createContext, useContext } from "react";
import { useRuntimeConfigVersion } from "../store";
import { getRuntimeConfigVersion } from "../lib/api";
import { useTheme } from "../theme";
import { colors, typo, radius, shadow, space, statusColor, btnSecondary } from "../design";


// Types


export type ToastLevel = "info" | "success" | "warning" | "error";

export interface Toast {
  id: string;
  title: string;
  message?: string;
  level: ToastLevel;
  durationMs?: number;
  action?: { label: string; onClick: () => void };
}

type ToastInput = Omit<Toast, "id">;

interface ToastContextValue {
  add: (toast: ToastInput) => void;
  remove: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue>({
  add: () => {},
  remove: () => {},
});


// Global emitter (works outside React tree)


let globalAdd: ((toast: ToastInput) => void) | null = null;

/** Fire a toast from anywhere — no React context needed. */
export function toast(input: ToastInput): void {
  if (globalAdd) globalAdd(input);
}

// Convenience helpers
toast.info = (title: string, message?: string) => toast({ title, message, level: "info" });
toast.success = (title: string, message?: string) => toast({ title, message, level: "success" });
toast.warning = (title: string, message?: string) => toast({ title, message, level: "warning" });
toast.error = (title: string, message?: string) => toast({ title, message, level: "error" });


// Provider


let toastCounter = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const version = useRuntimeConfigVersion();
  const { locale } = useTheme();
  const [toasts, setToasts] = useState<Array<Toast & { version: number }>>([]);
  const [expanded, setExpanded] = useState(false);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const recent = useRef(new Map<string, number>());
  const remove = useCallback((id: string) => {
    clearTimeout(timers.current.get(id)); timers.current.delete(id);
    setToasts(previous => previous.filter(value => value.id !== id));
  }, []);
  const add = useCallback((input: ToastInput) => {
    const current = getRuntimeConfigVersion(), now = Date.now();
    const signature = JSON.stringify([current, input.level, input.title, input.message]);
    // Repeated transport failures should not cover the workspace. Actionable
    // notifications remain distinct so a different action is never discarded.
    if (!input.action && recent.current.has(signature) && now - recent.current.get(signature)! < 30000) return;
    for (const [key, timestamp] of recent.current) if (now - timestamp >= 30000) recent.current.delete(key);
    if (!input.action) recent.current.set(signature, now);
    const id = `toast_${++toastCounter}_${now}`;
    setToasts(previous => [...previous.filter(value => value.version === current), { ...input, id, version: current }]);
    const duration = input.durationMs ?? (input.level === "error" ? 8000 : 4000);
    if (duration > 0) timers.current.set(id, setTimeout(() => remove(id), duration));
  }, [remove]);
  useEffect(() => {
    setToasts(previous => previous.filter(value => value.version === version)); setExpanded(false);
    recent.current.clear();
  }, [version]);
  useEffect(() => {
    const currentTimers = timers.current;
    globalAdd = add;
    return () => {
      if (globalAdd === add) globalAdd = null;
      for (const timer of currentTimers.values()) clearTimeout(timer);
      currentTimers.clear();
    };
  }, [add]);
  const current = toasts.filter(value => value.version === version);
  const priority: Record<ToastLevel, number> = { error: 0, warning: 1, info: 2, success: 3 };
  const visible = expanded ? current : [...current].sort((a, b) => priority[a.level] - priority[b.level]).slice(0, 3);

  return (
    <ToastContext.Provider value={{ add, remove }}>
      {children}
      {/* Toast container — fixed top-right */}
      <div
        role="region" aria-label={locale === "zh" ? "通知" : "Notifications"}
        style={{
          position: "fixed",
          top: space.lg,
          right: space.lg,
          zIndex: 10000,
          display: "flex",
          flexDirection: "column",
          gap: space.sm,
          maxWidth: "min(380px, calc(100vw - 32px))",
          maxHeight: "min(440px, 55vh)",
          overflowY: "auto",
          pointerEvents: "none",
        }}
      >
        {current.length > 3 && <button style={{ ...btnSecondary, pointerEvents: "auto" }} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? (locale === "zh" ? "收起通知" : "Show fewer") : (locale === "zh" ? `另有 ${current.length - 3} 条通知` : `${current.length - 3} more notifications`)}</button>}
        {visible.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => remove(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}


// Hook


export function useToast(): ToastContextValue {
  return useContext(ToastContext);
}


// Toast item


const levelConfig: Record<ToastLevel, { icon: string; bg: string; border: string; text: string }> = {
  info:    { icon: "ℹ", bg: colors.infoSoft, border: colors.info, text: colors.info },
  success: { icon: "✓", bg: colors.successSoft, border: colors.success, text: colors.success },
  warning: { icon: "!", bg: colors.warningSoft, border: colors.warning, text: colors.warning },
  error:   { icon: "X", bg: colors.dangerSoft, border: colors.danger, text: colors.danger },
};

function ToastItem({ toast: t, onDismiss }: { toast: Toast & { version: number }; onDismiss: () => void }) {
  const { locale } = useTheme();
  const cfg = levelConfig[t.level];

  return (
    <div
      role={t.level === "error" ? "alert" : "status"}
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderLeft: `3px solid ${cfg.border}`,
        borderRadius: radius.md,
        padding: `${space.md} ${space.lg}`,
        boxShadow: shadow.lg,
        pointerEvents: "auto",
        animation: "nousToastIn 0.25s ease-out",
        display: "flex",
        gap: space.sm,
      }}
    >
      {/* Icon */}
      <div
        style={{
          width: 24,
          height: 24,
          borderRadius: radius.full,
          background: cfg.bg,
          color: cfg.text,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: typo.sm,
          flexShrink: 0,
        }}
      >
        {cfg.icon}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: typo.base, fontWeight: typo.semibold, color: colors.text }}>
          {t.title}
        </div>
        {t.message && (
          <div style={{ fontSize: typo.sm, color: colors.textSecondary, marginTop: 2 }}>
            {t.message}
          </div>
        )}
        {t.action && (
          <button
            onClick={(e) => { e.stopPropagation(); if (t.version === getRuntimeConfigVersion()) t.action!.onClick(); onDismiss(); }}
            style={{
              marginTop: space.sm,
              fontSize: typo.xs,
              fontWeight: typo.medium,
              color: cfg.text,
              background: cfg.bg,
              border: "none",
              borderRadius: radius.sm,
              padding: `${space.xs} ${space.sm}`,
              cursor: "pointer",
              fontFamily: typo.font,
            }}
          >
            {t.action.label}
          </button>
        )}
      </div>

      {/* Dismiss */}
      <button
        onClick={onDismiss}
        aria-label={locale === "zh" ? `关闭通知：${t.title}` : `Dismiss notification: ${t.title}`}
        style={{
          background: "none",
          border: "none",
          color: colors.textTertiary,
          cursor: "pointer",
          fontSize: typo.md,
          padding: 0,
          lineHeight: 1,
          flexShrink: 0,
        }}
      >
        ×
      </button>
    </div>
  );
}
