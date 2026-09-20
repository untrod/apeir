/** Global command and Runtime search palette. */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { colors, fadeIn, radius, shadow, space, typo } from "../design";
import { globalSearch, type GlobalSearchResult } from "../lib/api";

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
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [searchResults, setSearchResults] = useState<GlobalSearchResult[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const localCommands = query.trim()
      ? commands.filter((command) => {
          const value = query.toLowerCase();
          return command.label.toLowerCase().includes(value)
            || command.category.toLowerCase().includes(value)
            || (command.keywords || []).some((keyword) => keyword.toLowerCase().includes(value));
        })
      : commands;
    const runtimeCommands: PaletteCommand[] = searchResults.map((result) => ({
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
    window.setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      globalSearch(query.trim(), 30)
        .then((response) => {
          if (!cancelled) setSearchResults(response.results || []);
        })
        .catch(() => {
          if (!cancelled) setSearchResults([]);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, query]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((index) => Math.min(index + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      filtered[safeIndex]?.action();
      if (filtered[safeIndex]) onClose();
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }, [filtered, safeIndex, onClose]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k" && open) {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.3)", zIndex: 1000 }} />
      <div style={{
        position: "fixed",
        top: "15%",
        left: "50%",
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
        <div style={{ padding: space.lg, borderBottom: `1px solid ${colors.borderLight}` }}>
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => { setQuery(event.target.value); setSelectedIndex(0); }}
            onKeyDown={handleKeyDown}
            placeholder="Search conversations, files, artifacts, traces, and commands"
            aria-label="Search APEIR"
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
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: space.sm }}>
          {filtered.length === 0 ? (
            <div style={{ textAlign: "center", padding: space.xl, color: colors.textTertiary, fontSize: typo.sm }}>
              No matching Runtime data or commands
            </div>
          ) : filtered.map((command, index) => {
            const selected = index === safeIndex;
            return (
              <div
                key={command.id}
                onClick={() => { command.action(); onClose(); }}
                onMouseEnter={() => setSelectedIndex(index)}
                style={{
                  display: "flex",
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
              </div>
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
          <span>Up/Down Navigate</span>
          <span>Enter Select</span>
          <span>Esc Dismiss</span>
        </div>
      </div>
    </>
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
