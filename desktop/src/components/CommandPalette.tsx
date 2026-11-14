/** Global command and Runtime search palette. */

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { colors, fadeIn, radius, shadow, space, typo } from "../design";
import { globalSearch, type GlobalSearchResult } from "../lib/api";
import { useTheme } from "../theme";
import { useRuntimeConfigVersion } from "../store";

export interface PaletteCommand {
  id: string;
  label: string;
  category: string;
  keywords?: string[];
  icon?: string;
  action: () => void;
}

interface CommandPaletteProps {
  commands: PaletteCommand[];
  open: boolean;
  onClose: () => void;
  onSearchResult?: (result: GlobalSearchResult) => void;
}

export function CommandPalette({
  commands,
  open,
  onClose,
  onSearchResult,
}: CommandPaletteProps) {
  const { locale } = useTheme();
  const version = useRuntimeConfigVersion();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [searchResults, setSearchResults] = useState<GlobalSearchResult[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "error">("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const resultsId = useId();

  const filtered = useMemo(() => {
    const localCommands = query.trim()
      ? commands.filter((command) => {
          const value = query.toLowerCase();
          return command.label.toLowerCase().includes(value)
            || command.category.toLowerCase().includes(value)
            || (command.keywords || []).some((keyword) => keyword.toLowerCase().includes(value));
        })
      : commands;
    const unique = [...new Map(searchResults.map(result => [`${result.kind}:${result.id}`, result])).values()];
    const runtimeCommands: PaletteCommand[] = unique.map((result) => ({
      id: `search-${result.kind}-${result.id}`,
      label: result.title,
      category: result.kind === "run" ? "Trace" : result.kind,
      keywords: [result.detail, result.path || ""],
      icon: result.kind.slice(0, 1).toUpperCase(),
      action: () => onSearchResult?.(result),
    }));
    return [...runtimeCommands, ...localCommands];
  }, [commands, onSearchResult, query, searchResults]);
  const safeIndex = Math.min(selectedIndex, Math.max(0, filtered.length - 1));

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSearchResults([]);
    setSelectedIndex(0);
    const trigger = document.activeElement as HTMLElement | null;
    dialogRef.current?.showModal();
    inputRef.current?.focus();
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, [open, version]);

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setSearchResults([]); setSearchState("idle");
      return;
    }
    let cancelled = false;
    const abort = new AbortController();
    setSearchResults([]); setSearchState("loading");
    const timer = window.setTimeout(() => {
      globalSearch(query.trim(), 30, abort.signal)
        .then((response) => {
          if (!cancelled) { setSearchResults(response.results || []); setSearchState("idle"); }
        })
        .catch(() => {
          if (!cancelled) { setSearchResults([]); setSearchState("error"); }
        });
    }, 180);
    return () => {
      cancelled = true;
      abort.abort();
      window.clearTimeout(timer);
    };
  }, [open, query, version]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((index) => Math.min(index + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const command = filtered[safeIndex];
      if (command) { onClose(); command.action(); }
    } else if (event.key === "Escape") {
      event.preventDefault(); event.stopPropagation();
      onClose();
    }
  }, [filtered, safeIndex, onClose]);

  if (!open) return null;
  return (
      <dialog ref={dialogRef} aria-label={t("Search and commands", "搜索与命令")} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose(); } }} style={{
        position: "fixed",
        top: "15%",
        left: "50%",
        margin: 0,
        padding: 0,
        transform: "translateX(-50%)",
        width: 600,
        maxWidth: "90vw",
        maxHeight: "65vh",
        background: colors.surface,
        borderRadius: radius.lg,
        boxShadow: shadow.xl,
        border: `1px solid ${colors.border}`,
        zIndex: 1001,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        ...fadeIn,
      }}>
        <div style={{ display: "flex", gap: space.sm, padding: space.lg, borderBottom: `1px solid ${colors.borderLight}` }}>
          <input
            ref={inputRef}
            role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls={resultsId}
            aria-activedescendant={filtered.length ? `${resultsId}-${safeIndex}` : undefined}
            value={query}
            onChange={(event) => { setQuery(event.target.value); setSelectedIndex(0); }}
            onKeyDown={handleKeyDown}
            placeholder={t("Search panels, conversations, files and runs", "搜索面板、会话、文件和运行记录")}
            aria-label={t("Search APEIR", "搜索 APEIR")}
            style={{
              width: "100%",
              border: "none",
              outline: "none",
              fontSize: typo.md,
              fontFamily: typo.font,
              color: colors.text,
              background: "transparent",
            }}
          />
          <button aria-label={t("Close search", "关闭搜索")} onClick={onClose} style={{ color: colors.textSecondary, background: "transparent", border: 0, cursor: "pointer" }}>×</button>
        </div>
        {searchState !== "idle" && <p role="status" style={{ fontSize: typo.sm, padding: `0 ${space.lg}`, color: colors.textSecondary }}>{searchState === "loading" ? t("Searching Runtime…", "正在搜索运行记录…") : t("Runtime search is unavailable. Panel commands still work.", "暂时无法搜索运行记录，面板命令仍可使用。")}</p>}
        <div id={resultsId} role="listbox" aria-label={t("Search results", "搜索结果")} style={{ flex: 1, overflowY: "auto", padding: space.sm }}>
          {filtered.length === 0 ? (
            <div style={{ textAlign: "center", padding: space.xl, color: colors.textTertiary, fontSize: typo.sm }}>
              {t("No matching Runtime data or commands", "未找到匹配的数据或命令")}
            </div>
          ) : filtered.map((command, index) => {
            const selected = index === safeIndex;
            return (
              <button type="button" role="option" aria-selected={selected} id={`${resultsId}-${index}`} tabIndex={-1}
                key={command.id}
                onClick={() => { onClose(); command.action(); }}
                onMouseEnter={() => setSelectedIndex(index)}
                style={{
                  display: "flex",
                  width: "100%", border: 0, textAlign: "left", fontFamily: "inherit",
                  alignItems: "center",
                  gap: space.md,
                  padding: `${space.sm} ${space.md}`,
                  borderRadius: radius.md,
                  background: selected ? colors.accentSoft : "transparent",
                  color: selected ? colors.accent : colors.text,
                  cursor: "pointer",
                  fontSize: typo.base,
                }}
              >
                <div style={{
                  width: 28,
                  height: 28,
                  borderRadius: radius.sm,
                  background: selected ? colors.accentMuted : colors.surfaceHover,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: typo.sm,
                  flexShrink: 0,
                }}>
                  {command.icon || ">"}
                </div>
                <div style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {command.label}
                </div>
                <span style={{ fontSize: typo.xs, color: colors.textTertiary, flexShrink: 0 }}>{command.category}</span>
              </button>
            );
          })}
        </div>
        <div style={{
          padding: `${space.sm} ${space.lg}`,
          borderTop: `1px solid ${colors.borderLight}`,
          fontSize: typo.xs,
          color: colors.textTertiary,
          display: "flex",
          gap: space.lg,
        }}>
          <span>↑ ↓ {t("Navigate", "选择")}</span>
          <span>Enter {t("Open", "打开")}</span>
          <span>Esc {t("Close", "关闭")}</span>
        </div>
      </dialog>
  );
}

export function createDefaultCommands(
  navigate: (page: string) => void,
  handlers: {
    onToggleInspector?: () => void;
    onToggleTheme?: () => void;
    onNewSession?: () => void;
    onScanNodes?: () => void;
  } = {},
): PaletteCommand[] {
  return [
    { id: "nav-chat", label: "Chat", category: "Navigation", keywords: ["messages", "conversation"], action: () => navigate("chat") },
    { id: "nav-tasks", label: "Tasks", category: "Navigation", keywords: ["jobs", "execution"], action: () => navigate("tasks") },
    { id: "nav-develop", label: "Developer Platform", category: "Navigation", keywords: ["projects", "runs", "experiments", "model lab"], action: () => navigate("develop") },
    { id: "nav-nodes", label: "Nodes", category: "Navigation", keywords: ["devices", "compute"], action: () => navigate("nodes") },
    { id: "nav-models", label: "Models", category: "Navigation", keywords: ["providers", "LLM"], action: () => navigate("models") },
    { id: "nav-workspace", label: "Workspace", category: "Navigation", keywords: ["files", "project"], action: () => navigate("workspace") },
    { id: "nav-settings", label: "Settings", category: "Navigation", keywords: ["preferences", "config"], action: () => navigate("settings") },
    { id: "act-inspector", label: "Toggle Inspector", category: "Action", keywords: ["debug", "trace"], action: () => handlers.onToggleInspector?.() },
    { id: "act-theme", label: "Toggle Theme", category: "Action", keywords: ["dark", "light"], action: () => handlers.onToggleTheme?.() },
    { id: "act-scan", label: "Scan Nodes", category: "Action", keywords: ["discover", "network"], action: () => handlers.onScanNodes?.() },
    { id: "act-new-session", label: "New Conversation", category: "Action", keywords: ["fresh", "clear"], action: () => handlers.onNewSession?.() },
  ];
}
