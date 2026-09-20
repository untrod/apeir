/**
 * ErrorBoundary — Catches React render errors and displays a diagnostic page
 * instead of a white screen.
 *
 * Also registers global window.onerror and unhandledrejection handlers.
 */

import React, { Component } from "react";
import { DiagnosticPage, type DiagnosticState } from "./DiagnosticPage";
import { resetUIState } from "../lib/migration";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    this.setState({ errorInfo });
    // Log to console for debugging
    console.error("[Nous ErrorBoundary] React render error:", error, errorInfo);
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      const diag: DiagnosticState = {
        errorTitle: "Application Render Error",
        errorSummary:
          this.state.error?.message ||
          "An unexpected error occurred while rendering the interface.",
        errorCode: "UI_RENDER_ERROR",
        errorDetail: this.state.error?.stack || null,
        componentStack: this.state.errorInfo?.componentStack || null,
        recoverable: true,
        onRetry: this.handleReset,
        onResetUI: () => {
          resetUIState();
          this.handleReset();
        },
      };
      return <DiagnosticPage {...diag} />;
    }
    return this.props.children;
  }
}

/**
 * Hook-style error boundary wrapper (for use in functional components).
 * Registers global error handlers for uncaught errors outside React tree.
 */
export function registerGlobalErrorHandlers(
  onFatalError: (diag: DiagnosticState) => void,
): () => void {
  const cleanupFns: (() => void)[] = [];

  // window.onerror — catches uncaught synchronous errors
  const prevOnError = window.onerror;
  window.onerror = (
    message: string | Event,
    source?: string,
    lineno?: number,
    colno?: number,
    error?: Error,
  ): boolean => {
    const msg = typeof message === "string" ? message : "Unknown error";
    onFatalError({
      errorTitle: "Unhandled Error",
      errorSummary: msg,
      errorCode: "GLOBAL_ONERROR",
      errorDetail: error?.stack || `${source}:${lineno}:${colno}`,
      recoverable: true,
    });
    // Also call previous handler if any
    if (prevOnError) {
      prevOnError(message, source, lineno, colno, error);
    }
    return true; // Prevent default browser error dialog
  };
  cleanupFns.push(() => {
    window.onerror = prevOnError;
  });

  // unhandledrejection — catches unhandled Promise rejections
  const prevRejection = window.onunhandledrejection;
  window.onunhandledrejection = (event: PromiseRejectionEvent): void => {
    const reason = event.reason;
    const msg =
      reason instanceof Error
        ? reason.message
        : typeof reason === "string"
          ? reason
          : "Unhandled Promise rejection";
    onFatalError({
      errorTitle: "Unhandled Promise Rejection",
      errorSummary: msg,
      errorCode: "UNHANDLED_REJECTION",
      errorDetail: reason instanceof Error ? reason.stack : String(reason),
      recoverable: true,
    });
    if (prevRejection) {
      prevRejection.call(window, event);
    }
  };
  cleanupFns.push(() => {
    window.onunhandledrejection = prevRejection;
  });

  return () => cleanupFns.forEach((fn) => fn());
}
