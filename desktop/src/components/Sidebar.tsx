/**
 * Sidebar — Minimal icon-navigation rail for the Chat-first Experience.
 * Supports collapsed (icon-only) and expanded (icon + label) modes.
 */

import React from "react";
import { colors, typo, radius, space } from "../design";
import { useTheme } from "../theme";

export type NavPage = "chat" | "tasks" | "develop" | "documents" | "environments" | "simulations" | "nodes" | "models" | "workspace" | "settings";

interface NavItem { page: NavPage; label: string; short: string; }

const NAV_ITEMS: NavItem[] = [
  { page: "chat",      label: "Chat",      short: "C" },
  { page: "tasks",     label: "Tasks",     short: "T" },
  { page: "develop",   label: "Develop",   short: "D" },
  { page: "documents", label: "Documents", short: "P" },
  { page: "environments", label: "Environments", short: "E" },
  { page: "simulations", label: "Simulations", short: "S" },
  { page: "nodes",     label: "Nodes",     short: "N" },
  { page: "models",    label: "Models",    short: "M" },
  { page: "workspace", label: "Workspace", short: "W" },
];

interface SidebarProps {
  currentPage: NavPage;
  onNavigate: (page: NavPage) => void;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  taskCount?: number;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({
  currentPage, onNavigate, inspectorOpen, onToggleInspector, taskCount, collapsed, onToggleCollapse,
}: SidebarProps) {
  const { resolved, toggle: toggleTheme } = useTheme();
  const w = collapsed ? 48 : 160;

  return (
    <nav style={{
      width: w, minWidth: w,
      height: "100%",
      background: colors.surface,
      borderRight: `1px solid ${colors.border}`,
      display: "flex", flexDirection: "column",
      transition: "width 0.15s ease",
      overflow: "hidden",
      flexShrink: 0, userSelect: "none",
    }}>
      {/* Logo */}
      <div style={{
        padding: collapsed ? space.sm : `${space.md} ${space.sm}`,
        borderBottom: `1px solid ${colors.borderLight}`,
        textAlign: "center",
      }}>
        <div style={{ fontSize: typo.md, fontWeight: typo.bold, color: colors.text, letterSpacing: "-0.5px" }}>
          {collapsed ? "A" : "APEIR"}
        </div>
      </div>

      {/* Nav items */}
      <div style={{ flex: 1, padding: space.xs }}>
        {NAV_ITEMS.map((item) => {
          const active = currentPage === item.page;
          return (
            <button
              key={item.page}
              onClick={() => onNavigate(item.page)}
              title={item.label}
              style={{
                display: "flex", alignItems: "center", gap: space.sm,
                width: "100%", padding: collapsed ? space.sm : `${space.sm} ${space.md}`,
                marginBottom: 1,
                border: "none", borderRadius: radius.md,
                background: active ? colors.accentSoft : "transparent",
                color: active ? colors.accent : colors.textSecondary,
                fontSize: typo.sm, fontWeight: active ? typo.semibold : typo.normal,
                fontFamily: typo.font, cursor: "pointer",
                transition: "background 0.12s, color 0.12s",
                textAlign: "left", justifyContent: collapsed ? "center" : "flex-start",
              }}
            >
              <span style={{ fontSize: typo.xs, fontWeight: typo.semibold, width: 24, textAlign: "center", flexShrink: 0 }}>{item.short}</span>
              {!collapsed && <span>{item.label}</span>}
              {item.page === "tasks" && taskCount && taskCount > 0 ? (
                <span style={{
                  marginLeft: "auto", background: colors.accent, color: colors.textInverse,
                  fontSize: "10px", fontWeight: typo.bold, padding: "1px 5px",
                  borderRadius: radius.full, minWidth: 18, textAlign: "center",
                }}>
                  {taskCount}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {/* Bottom */}
      <div style={{ padding: space.xs, borderTop: `1px solid ${colors.borderLight}` }}>
        <button onClick={onToggleInspector} title="Inspector"
          style={{
            display: "flex", alignItems: "center", gap: space.sm,
            width: "100%", padding: collapsed ? space.sm : `${space.sm} ${space.md}`,
            marginBottom: 1, border: "none", borderRadius: radius.md,
            background: inspectorOpen ? colors.purpleSoft : "transparent",
            color: inspectorOpen ? colors.purple : colors.textSecondary,
            fontSize: typo.sm, fontFamily: typo.font, cursor: "pointer",
            justifyContent: collapsed ? "center" : "flex-start",
          }}
        >
          <span style={{ fontSize: typo.xs, fontWeight: typo.semibold, width: 24, textAlign: "center" }}>I</span>
          {!collapsed && <span>Inspector</span>}
        </button>

        <button onClick={() => onNavigate("settings")} title="Settings"
          style={{
            display: "flex", alignItems: "center", gap: space.sm,
            width: "100%", padding: collapsed ? space.sm : `${space.sm} ${space.md}`,
            marginBottom: 1, border: "none", borderRadius: radius.md,
            background: currentPage === "settings" ? colors.accentSoft : "transparent",
            color: currentPage === "settings" ? colors.accent : colors.textSecondary,
            fontSize: typo.sm, fontFamily: typo.font, cursor: "pointer",
            justifyContent: collapsed ? "center" : "flex-start",
          }}
        >
          <span style={{ fontSize: typo.xs, fontWeight: typo.semibold, width: 24, textAlign: "center" }}>S</span>
          {!collapsed && <span>Settings</span>}
        </button>

        <button onClick={toggleTheme} title={`${resolved === "dark" ? "Light" : "Dark"} mode`}
          style={{
            display: "flex", alignItems: "center", gap: space.sm,
            width: "100%", padding: collapsed ? space.sm : `${space.sm} ${space.md}`,
            border: "none", borderRadius: radius.md,
            background: "transparent", color: colors.textSecondary,
            fontSize: typo.sm, fontFamily: typo.font, cursor: "pointer",
            justifyContent: collapsed ? "center" : "flex-start",
          }}
        >
          <span style={{ fontSize: typo.md, width: 24, textAlign: "center" }}>
            {resolved === "dark" ? "L" : "D"}
          </span>
          {!collapsed && <span>{resolved === "dark" ? "Light" : "Dark"}</span>}
        </button>

        <button onClick={onToggleCollapse} title={collapsed ? "Expand" : "Collapse"}
          style={{
            display: "flex", justifyContent: "center", width: "100%",
            padding: space.xs, marginTop: 2,
            border: "none", borderRadius: radius.sm,
            background: "transparent", color: colors.textTertiary,
            fontSize: typo.xs, cursor: "pointer",
          }}
        >{collapsed ? "▸" : "◂"}</button>
      </div>
    </nav>
  );
}
