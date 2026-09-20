/**
 * BootstrapScreen — Visual startup sequence for Nous Desktop.
 *
 * Displays each bootstrap state with progress bar, status messages,
 * and contextual action buttons. No state renders blank.
 */

import React from "react";
import { colors, typo, radius, space, btnPrimary, btnSecondary } from "../design";
import type { BootstrapStatus, BootstrapState } from "../lib/bootstrap";
import { STATE_MESSAGES } from "../lib/bootstrap";

interface BootstrapScreenProps {
  status: BootstrapStatus;
  onRetry: () => void;
  onStartRuntime: () => void;
  onResetSession: () => void;
  onCreateWorkspace: () => void;
  onOpenLogs: () => void;
  onResetUI: () => void;
  onProceedToOnboarding: () => void;
  onProceedToDashboard: () => void;
}

function statusDot(ok: boolean, label: string) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: typo.sm,
        color: ok ? colors.success : colors.textTertiary,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: ok ? colors.success : colors.borderLight,
          flexShrink: 0,
        }}
      />
      {label}
    </div>
  );
}

export function BootstrapScreen({
  status,
  onRetry,
  onStartRuntime,
  onResetSession,
  onCreateWorkspace,
  onOpenLogs,
  onResetUI,
  onProceedToOnboarding,
  onProceedToDashboard,
}: BootstrapScreenProps) {
  const isError =
    status.state === "recoverable_error" || status.state === "fatal_error";
  const isReady = status.state === "ready";
  const needsOnboarding = status.state === "onboarding_required";

  return (
    <div
      style={{
        minHeight: "100vh",
        background: colors.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: space.xl,
      }}
    >
      <div
        style={{
          width: 420,
          maxWidth: "90vw",
          textAlign: "center",
        }}
      >
        {/* Logo */}
        <div
          style={{
            fontSize: 36,
            marginBottom: space.lg,
            opacity: isError ? 0.6 : 1,
          }}
        >
          ●
        </div>

        <h1
          style={{
            fontSize: typo.xxl,
            fontWeight: typo.bold,
            color: colors.text,
            margin: `0 0 ${space.xs} 0`,
          }}
        >
          APEIR
        </h1>

        {/* State message */}
        <p
          style={{
            fontSize: typo.md,
            color: isError ? colors.danger : colors.textSecondary,
            margin: `0 0 ${space.xl} 0`,
            lineHeight: typo.relaxed,
          }}
        >
          {status.errorMessage ||
            STATE_MESSAGES[status.state] ||
            status.progressMessage}
        </p>

        {/* Progress bar */}
        {!isError && !isReady && !needsOnboarding && (
          <div
            style={{
              height: 3,
              background: colors.borderLight,
              borderRadius: 2,
              marginBottom: space.xl,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${Math.max(2, status.progress)}%`,
                background: colors.accent,
                borderRadius: 2,
                transition: "width 0.4s ease",
              }}
            />
          </div>
        )}

        {/* Checklist */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: space.sm,
            alignItems: "center",
            marginBottom: space.xl,
          }}
        >
          {statusDot(status.runtime.reachable, "Runtime reachable")}
          {statusDot(status.session.established, "Session established")}
          {statusDot(status.workspace.exists, "Workspace ready")}
          {statusDot(status.provider.configured, "Providers configured")}
        </div>

        {/* Warnings */}
        {status.warnings.length > 0 && (
          <div
            style={{
              textAlign: "left",
              marginBottom: space.lg,
              padding: space.md,
              background: colors.warningSoft,
              borderRadius: radius.md,
              fontSize: typo.sm,
              color: colors.warning,
            }}
          >
            {status.warnings.map((w, i) => (
              <div key={i}>Warning: {w}</div>
            ))}
          </div>
        )}

        {/* Error details */}
        {isError && status.errorCode && (
          <div
            style={{
              textAlign: "center",
              marginBottom: space.lg,
            }}
          >
            <code
              style={{
                fontSize: typo.xs,
                fontFamily: typo.mono,
                color: colors.textTertiary,
                background: colors.inlineCodeBg,
                padding: "2px 8px",
                borderRadius: radius.sm,
              }}
            >
              {status.errorCode}
            </code>
          </div>
        )}

        {/* Action buttons */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: space.sm,
          }}
        >
          {/* Ready state */}
          {isReady && (
            <button onClick={onProceedToDashboard} style={btnPrimary}>
              Enter Dashboard →
            </button>
          )}

          {/* Onboarding needed */}
          {needsOnboarding && (
            <button onClick={onProceedToOnboarding} style={btnPrimary}>
              Start Setup →
            </button>
          )}

          {/* Error recovery */}
          {isError && status.recoverable && (
            <>
              <button onClick={onRetry} style={btnPrimary}>
                Retry
              </button>
              <button onClick={onStartRuntime} style={btnSecondary}>
                Restart Runtime
              </button>
              <button onClick={onResetSession} style={btnSecondary}>
                Re-establish Session
              </button>
            </>
          )}

          {isError && !status.recoverable && (
            <div
              style={{
                padding: space.md,
                background: colors.dangerSoft,
                borderRadius: radius.md,
                color: colors.danger,
                fontSize: typo.sm,
                marginBottom: space.sm,
              }}
            >
              This error cannot be automatically recovered. Please check the logs
              for more information.
            </div>
          )}

          {/* Always available */}
          <button onClick={onOpenLogs} style={btnSecondary}>
            Open Logs
          </button>

          <button onClick={onResetUI} style={btnSecondary}>
            Reset UI State
          </button>

          {needsOnboarding && !isError && (
            <button
              onClick={onProceedToDashboard}
              style={{
                ...btnSecondary,
                fontSize: typo.sm,
                color: colors.textTertiary,
              }}
            >
              Skip setup (limited mode)
            </button>
          )}
        </div>

        {/* Version */}
        <p
          style={{
            marginTop: space.xxl,
            fontSize: typo.xs,
            color: colors.textTertiary,
          }}
        >
          APEIR Runtime v0.1.0-rc1
        </p>
      </div>
    </div>
  );
}
