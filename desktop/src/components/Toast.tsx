/**
 * Toast — non-intrusive notification system for real-time runtime events.
 *
 * Uses a lightweight pub/sub pattern so any component can fire a toast
 * without prop threading. Toasts auto-dismiss and stack at the top-right.
 */

import React, { useState, useCallback, useEffect, createContext, useContext } from "react";
import { colors, typo, radius, shadow, space, statusColor } from "../design";


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
  const [toasts, setToasts] = useState<Toast[]>([]);

  const add = useCallback((input: ToastInput) => {
    const id = `toast_${++toastCounter}_${Date.now()}`;
    const t: Toast = { ...input, id };
    setToasts((prev) => [...prev, t]);

    // Auto-dismiss
    const duration = input.durationMs ?? (input.level === "error" ? 8000 : 4000);
    if (duration > 0) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== id));
      }, duration);
    }
  }, []);

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Register global emitter
  useEffect(() => {
    globalAdd = add;
    return () => { globalAdd = null; };
  }, [add]);

  return (
    <ToastContext.Provider value={{ add, remove }}>
      {children}
      {/* Toast container — fixed top-right */}
      <div
        style={{
          position: "fixed",
          top: space.lg,
          right: space.lg,
          zIndex: 10000,
          display: "flex",
          flexDirection: "column",
          gap: space.sm,
          maxWidth: 380,
          pointerEvents: "none",
        }}
      >
        {toasts.map((t) => (
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

function ToastItem({ toast: t, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const cfg = levelConfig[t.level];

  return (
    <div
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
            onClick={(e) => { e.stopPropagation(); t.action!.onClick(); onDismiss(); }}
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
