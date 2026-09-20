import React from "react";
import { colors, typo, radius, space } from "../design";
import { useConversations, type Conversation } from "../store";

interface SessionBarProps {
  activeId?: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function SessionBar({ activeId, onSelect, onNew, collapsed, onToggleCollapse }: SessionBarProps) {
  const conversations = useConversations();
  const active = conversations.filter((conversation) => !conversation.archived);
  const archived = conversations.filter((conversation) => conversation.archived);
  const width = collapsed ? 56 : 260;

  return (
    <div
      style={{
        width,
        minWidth: width,
        background: colors.surface,
        borderRight: `1px solid ${colors.border}`,
        display: "flex",
        flexDirection: "column",
        transition: "width 0.2s ease",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: space.sm,
          borderBottom: `1px solid ${colors.borderLight}`,
          minHeight: 44,
          gap: space.xs,
        }}
      >
        {!collapsed && (
          <span
            style={{
              fontSize: typo.xs,
              fontWeight: typo.semibold,
              color: colors.textTertiary,
              textTransform: "uppercase",
              flex: 1,
            }}
          >
            Conversations
          </span>
        )}
        <button onClick={onNew} title="New conversation" style={iconButtonStyle}>
          +
        </button>
        <button onClick={onToggleCollapse} title={collapsed ? "Expand" : "Collapse"} style={iconButtonStyle}>
          {collapsed ? "›" : "‹"}
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: space.xs }}>
        {active.length === 0 ? (
          <div style={{ padding: space.md, textAlign: "center", fontSize: typo.xs, color: colors.textTertiary }}>
            {collapsed ? "" : "No conversations"}
          </div>
        ) : (
          active.map((conversation) => (
            <SessionItem
              key={conversation.id}
              conversation={conversation}
              active={conversation.id === activeId}
              collapsed={collapsed}
              onClick={() => onSelect(conversation.id)}
            />
          ))
        )}

        {archived.length > 0 && !collapsed && (
          <>
            <div style={{ padding: `${space.sm} ${space.sm} ${space.xs}`, fontSize: typo.xs, color: colors.textTertiary, fontWeight: typo.semibold }}>
              Archived
            </div>
            {archived.map((conversation) => (
              <SessionItem
                key={conversation.id}
                conversation={conversation}
                active={false}
                collapsed={collapsed}
                onClick={() => onSelect(conversation.id)}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function SessionItem({ conversation, active, collapsed, onClick }: {
  conversation: Conversation;
  active: boolean;
  collapsed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={conversation.title}
      style={{
        display: "flex",
        alignItems: "center",
        gap: space.sm,
        width: "100%",
        padding: collapsed ? space.sm : `${space.sm} ${space.md}`,
        border: "none",
        borderRadius: radius.md,
        background: active ? colors.accentSoft : "transparent",
        color: active ? colors.accent : colors.text,
        fontSize: typo.sm,
        fontFamily: typo.font,
        cursor: "pointer",
        textAlign: "left",
        transition: "background 0.1s",
        marginBottom: 1,
      }}
    >
      <span
        style={{
          width: 24,
          height: 24,
          borderRadius: radius.sm,
          background: active ? colors.accentMuted : colors.surfaceHover,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: typo.xs,
          flexShrink: 0,
          color: active ? colors.accent : colors.textTertiary,
        }}
      >
        {conversation.pinned ? "★" : "◇"}
      </span>
      {!collapsed && (
        <>
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: active ? typo.semibold : typo.normal }}>
            {conversation.title || "New Conversation"}
          </span>
          <span style={{ fontSize: typo.xs, color: colors.textTertiary }}>{conversation.message_count}</span>
        </>
      )}
    </button>
  );
}

const iconButtonStyle: React.CSSProperties = {
  width: 30,
  height: 30,
  borderRadius: radius.sm,
  border: "none",
  background: "transparent",
  color: colors.textSecondary,
  cursor: "pointer",
  fontSize: typo.md,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};
