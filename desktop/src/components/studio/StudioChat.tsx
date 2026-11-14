import { useCallback, useEffect, useState } from "react";
import { ChatView } from "../ChatView";
import { SessionBar } from "../SessionBar";
import { StudioIcon } from "./StudioIcon";
import type { PanelProps } from "./StudioPanels";

/** Existing conversation store and Chat session; only panel presentation is local. */
export function StudioChat({ locale, inspect, open, navigation, onDraftChange }: PanelProps) {
  const [conversation, setConversation] = useState<string>();
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState("");
  const protect = useCallback((value: boolean) => { setDirty(value); onDraftChange(value); }, [onDraftChange]);
  useEffect(() => { if (navigation?.conversationId) { setConversation(navigation.conversationId); setHistory(false); } }, [navigation]);
  const [history, setHistory] = useState(false);
  const [generation, setGeneration] = useState(0);
  const newConversation = () => { if (dirty) { setMessage(t("Send or clear the current draft before starting another conversation.", "请先发送或清空当前草稿，再新建对话。")); return; } setMessage(""); setConversation(undefined); setGeneration(value => value + 1); };
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  return <section className="studio-chat" aria-label={t("AI conversation", "AI 对话")}>
    <header className="studio-chat-toolbar">
      <button aria-pressed={history} onClick={() => setHistory(value => !value)}><StudioIcon name="history" />{t("Conversations", "会话历史")}</button>
      <button onClick={newConversation}><StudioIcon name="add" />{t("New conversation", "新建对话")}</button>
    </header>
    {message && <p role="status">{message}</p>}
    <div className="studio-chat-body">
      {history && <SessionBar activeId={conversation} onSelect={id => { if (id === conversation) { setHistory(false); return; } if (dirty) { setMessage(t("Send or clear the current draft before switching conversations.", "请先发送或清空当前草稿，再切换会话。")); return; } setMessage(""); setConversation(id); setHistory(false); }} onNew={newConversation} collapsed={false} onToggleCollapse={() => setHistory(false)} locale={locale} showHeader={false} />}
      <div className="studio-chat-content"><ChatView onDraftChange={protect} key={generation} locale={locale} conversationId={conversation} onConversationCreated={setConversation} onOpenPanel={open} onCardClick={event => {
        const data = event.payload || {};
        if (data.task_id) inspect({ kind: "task", taskId: String(data.task_id) });
        else if (data.trace_id) inspect({ kind: "trace", traceId: String(data.trace_id) });
        else if (event.event_type.startsWith("node.") && data.node_id) inspect({ kind: "node", nodeId: String(data.node_id) });
        else open("operations");
      }} onTraceClick={traceId => inspect({ kind: "trace", traceId })} /></div>
    </div>
  </section>;
}
