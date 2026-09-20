/**
 * Composer — Floating chat input with draft persistence, attachments, and constraints.
 *
 * Features:
 *   - Multi-line auto-growing textarea
 *   - Draft auto-save to localStorage per conversation
 *   - File/image/workspace attachments via drag-drop and paste
 *   - Stop generation button (visible during streaming)
 *   - Model selector, node target, privacy level, budget constraint
 *   - Cmd+Enter to send, Shift+Enter for newline
 */

import React, { useState, useRef, useEffect, useCallback } from "react";
import { colors, typo, radius, shadow, space } from "../design";
import type { Model, Node } from "../store";


// Types


export interface ComposerAttachment {
  id: string;
  name: string;
  kind: "file" | "image" | "workspace";
  size_bytes?: number;
  preview_url?: string;
}

export interface ComposerConstraints {
  model_id?: string;
  node_id?: string;
  agent_mode?: "agent" | "read_only" | "chat";
  privacy_level?: "standard" | "sensitive" | "strict";
  budget_limit_usd?: number;
}

export interface ComposerProps {
  onSend: (text: string, attachments: ComposerAttachment[], constraints: ComposerConstraints) => void;
  onStop: () => void;
  disabled: boolean;
  streaming: boolean;
  models: Model[];
  nodes: Node[];
  conversationId?: string;
}


// Draft persistence


function loadDraft(conversationId?: string): string {
  if (!conversationId) return "";
  try {
    return localStorage.getItem(`nous_draft_${conversationId}`) || "";
  } catch { return ""; }
}

function saveDraft(conversationId: string | undefined, text: string): void {
  if (!conversationId) return;
  try {
    if (text.trim()) {
      localStorage.setItem(`nous_draft_${conversationId}`, text);
    } else {
      localStorage.removeItem(`nous_draft_${conversationId}`);
    }
  } catch { /* quota exceeded — silent fail */ }
}


// Composer


export function Composer({
  onSend, onStop, disabled, streaming,
  models, nodes, conversationId,
}: ComposerProps) {
  const [text, setText] = useState(() => loadDraft(conversationId));
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [constraints, setConstraints] = useState<ComposerConstraints>({});
  const [showConstraints, setShowConstraints] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Persist draft
  useEffect(() => {
    const timer = setInterval(() => saveDraft(conversationId, text), 2000);
    return () => {
      clearInterval(timer);
      saveDraft(conversationId, text);
    };
  }, [conversationId, text]);

  // Reload draft when conversation changes
  useEffect(() => {
    setText(loadDraft(conversationId));
    setAttachments([]);
  }, [conversationId]);

  // Auto-resize
  useEffect(() => {
    const el = inputRef.current;
    if (el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 200) + "px"; }
  }, [text]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if ((!trimmed && attachments.length === 0) || disabled) return;
    onSend(trimmed, attachments, constraints);
    setText("");
    setAttachments([]);
    saveDraft(conversationId, "");
  }, [text, attachments, constraints, disabled, conversationId, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // File handling
  const addFiles = useCallback((files: FileList | File[]) => {
    const newAttachments: ComposerAttachment[] = Array.from(files).map((f) => ({
      id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      name: f.name,
      kind: f.type.startsWith("image/") ? "image" : "file",
      size_bytes: f.size,
      preview_url: f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined,
    }));
    setAttachments((prev) => [...prev, ...newAttachments]);
  }, []);

  const handlePaste = (e: React.ClipboardEvent) => {
    if (e.clipboardData.files.length > 0) {
      e.preventDefault();
      addFiles(e.clipboardData.files);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files);
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const enabledModels = models.filter((m) => m.state !== "disabled");
  const onlineNodes = nodes.filter((n) => n.online);

  return (
    <div
      style={{
        padding: `${space.lg} ${space.xl}`,
        background: `linear-gradient(180deg, transparent 0%, ${colors.bg} 40%)`,
        position: "relative",
      }}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div style={{
          position: "absolute", inset: 0,
          background: `${colors.accentSoft}80`,
          border: `2px dashed ${colors.accent}`,
          borderRadius: radius.lg,
          display: "flex", alignItems: "center", justifyContent: "center",
          zIndex: 10, pointerEvents: "none",
        }}>
          <span style={{ fontSize: typo.md, color: colors.accent, fontWeight: typo.semibold }}>
            Drop files to attach
          </span>
        </div>
      )}

      {/* Attachments preview */}
      {attachments.length > 0 && (
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap", marginBottom: space.sm }}>
          {attachments.map((att) => (
            <div key={att.id} style={{
              display: "flex", alignItems: "center", gap: space.xs,
              padding: `${space.xs} ${space.sm}`,
              background: colors.surface, border: `1px solid ${colors.border}`,
              borderRadius: radius.md, fontSize: typo.xs,
            }}>
              <span style={{ color: colors.textTertiary }}>{att.kind.toUpperCase()}</span>
              <span style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {att.name}
              </span>
              <button onClick={() => removeAttachment(att.id)} style={{
                background: "none", border: "none", cursor: "pointer",
                color: colors.textTertiary, fontSize: typo.sm, padding: 0,
              }}>×</button>
            </div>
          ))}
        </div>
      )}

      {/* Constraints bar */}
      {showConstraints && (
        <div style={{
          display: "flex", gap: space.sm, flexWrap: "wrap",
          marginBottom: space.sm, padding: space.sm,
          background: colors.surface, borderRadius: radius.md,
          border: `1px solid ${colors.border}`,
        }}>
          {/* Execution mode */}
          <select
            value={constraints.agent_mode || "agent"}
            onChange={(e) => setConstraints((c) => ({
              ...c,
              agent_mode: e.target.value as ComposerConstraints["agent_mode"],
            }))}
            style={{
              padding: `${space.xs} ${space.sm}`, fontSize: typo.xs,
              fontFamily: typo.font, color: colors.text,
              background: colors.surfaceHover, border: `1px solid ${colors.border}`,
              borderRadius: radius.sm,
            }}
          >
            <option value="agent">Mode: Agent</option>
            <option value="read_only">Mode: Read only</option>
            <option value="chat">Mode: Chat only</option>
          </select>

          {/* Model selector */}
          <select
            value={constraints.model_id || ""}
            onChange={(e) => setConstraints((c) => ({ ...c, model_id: e.target.value || undefined }))}
            style={{
              padding: `${space.xs} ${space.sm}`, fontSize: typo.xs,
              fontFamily: typo.font, color: colors.text,
              background: colors.surfaceHover, border: `1px solid ${colors.border}`,
              borderRadius: radius.sm,
            }}
          >
            <option value="">Model: Default</option>
            {enabledModels.slice(0, 10).map((m) => (
              <option key={m.id} value={m.id}>{m.display_name}</option>
            ))}
          </select>

          {/* Node target */}
          <select
            value={constraints.node_id || ""}
            onChange={(e) => setConstraints((c) => ({ ...c, node_id: e.target.value || undefined }))}
            style={{
              padding: `${space.xs} ${space.sm}`, fontSize: typo.xs,
              fontFamily: typo.font, color: colors.text,
              background: colors.surfaceHover, border: `1px solid ${colors.border}`,
              borderRadius: radius.sm,
            }}
          >
            <option value="">Node: Auto</option>
            {onlineNodes.slice(0, 10).map((n) => (
              <option key={n.id} value={n.id}>{n.name}</option>
            ))}
          </select>

          {/* Privacy */}
          <select
            value={constraints.privacy_level || "standard"}
            onChange={(e) => setConstraints((c) => ({ ...c, privacy_level: e.target.value as ComposerConstraints["privacy_level"] }))}
            style={{
              padding: `${space.xs} ${space.sm}`, fontSize: typo.xs,
              fontFamily: typo.font, color: colors.text,
              background: colors.surfaceHover, border: `1px solid ${colors.border}`,
              borderRadius: radius.sm,
            }}
          >
            <option value="standard">Privacy: Standard</option>
            <option value="sensitive">Privacy: Sensitive</option>
            <option value="strict">Privacy: Strict (local only)</option>
          </select>

          {/* Budget */}
          <input
            type="number"
            placeholder="Budget limit ($)"
            value={constraints.budget_limit_usd ?? ""}
            onChange={(e) => setConstraints((c) => ({ ...c, budget_limit_usd: e.target.value ? parseFloat(e.target.value) : undefined }))}
            style={{
              width: 110, padding: `${space.xs} ${space.sm}`, fontSize: typo.xs,
              fontFamily: typo.font, color: colors.text,
              background: colors.surfaceHover, border: `1px solid ${colors.border}`,
              borderRadius: radius.sm,
            }}
          />
        </div>
      )}

      {/* Input area */}
      <div style={{
        display: "flex", alignItems: "flex-end", gap: space.sm,
        background: colors.surface,
        borderRadius: radius.lg,
        border: `1px solid ${dragOver ? colors.accent : colors.border}`,
        padding: `${space.sm} ${space.sm} ${space.sm} ${space.lg}`,
        boxShadow: shadow.card,
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}>
        <textarea
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={
            attachments.length > 0
              ? "Add a message about these files..."
              : "Ask APEIR to plan, execute, or verify..."
          }
          disabled={disabled && !streaming}
          style={{
            flex: 1, border: "none", background: "transparent",
            fontSize: typo.base, fontFamily: typo.font,
            color: colors.text, resize: "none", outline: "none",
            maxHeight: 200, lineHeight: typo.relaxed,
            padding: `${space.xs} 0`,
          }}
          rows={1}
        />

        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Attach files"
            style={iconBtnStyle}
          >+</button>
          <input
            ref={fileInputRef} type="file" multiple
            onChange={(e) => e.target.files && addFiles(e.target.files)}
            style={{ display: "none" }}
          />

          {/* Constraints toggle */}
          <button
            onClick={() => setShowConstraints(!showConstraints)}
            title="Constraints"
            style={{
              ...iconBtnStyle,
              background: showConstraints ? colors.accentSoft : "transparent",
              color: showConstraints ? colors.accent : colors.textTertiary,
            }}
          >...</button>

          {/* Stop / Send */}
          {streaming ? (
            <button
              onClick={onStop}
              title="Stop generation"
              style={{
                ...iconBtnStyle,
                width: 36, height: 36,
                background: colors.danger, color: colors.textInverse,
                borderRadius: radius.md,
              }}
            >■</button>
          ) : (
            <button
              onClick={handleSend}
              disabled={disabled || (!text.trim() && attachments.length === 0)}
              title="Send (Enter)"
              style={{
                ...iconBtnStyle,
                width: 36, height: 36,
                background: (text.trim() || attachments.length > 0) ? colors.accent : colors.border,
                color: (text.trim() || attachments.length > 0) ? colors.textInverse : colors.textTertiary,
                borderRadius: radius.md,
                opacity: (text.trim() || attachments.length > 0) ? 1 : 0.5,
              }}
            >↑</button>
          )}
        </div>
      </div>

      {/* Footer hint */}
      <div style={{
        textAlign: "center", marginTop: space.sm,
        fontSize: typo.xs, color: colors.textTertiary,
        display: "flex", justifyContent: "space-between",
      }}>
        <span>Enter to send · Shift+Enter new line</span>
        <span>
          {constraints.model_id && `Model: ${models.find(m => m.id === constraints.model_id)?.display_name || constraints.model_id}`}
          {constraints.budget_limit_usd && ` · Budget: $${constraints.budget_limit_usd}`}
          {constraints.privacy_level === "strict" && " · Privacy: Strict"}
          {constraints.privacy_level === "sensitive" && " · Privacy: Sensitive"}
        </span>
      </div>
    </div>
  );
}

const iconBtnStyle: React.CSSProperties = {
  width: 32, height: 32,
  border: "none", borderRadius: radius.sm,
  cursor: "pointer", fontSize: typo.md,
  display: "flex", alignItems: "center", justifyContent: "center",
  background: "transparent", color: colors.textTertiary,
  transition: "background 0.15s",
};
