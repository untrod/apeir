import { useState } from "react";
import { ChatView } from "../ChatView";
import { SessionBar } from "../SessionBar";
import { StudioIcon } from "./StudioIcon";
import type { PanelProps } from "./StudioPanels";

/** Existing conversation store and Chat session; only panel presentation is local. */
export function StudioChat({ locale, inspect, open }: PanelProps) {
  const [conversation, setConversation] = useState<string>();
  const [history, setHistory] = useState(false);
  const [generation, setGeneration] = useState(0);
  const newConversation = () => { setConversation(undefined); setGeneration(value => value + 1); };
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  return <section className="studio-chat" aria-label={t("AI conversation", "AI 对话")}>
    <header className="studio-chat-toolbar">
      <button aria-pressed={history} onClick={() => setHistory(value => !value)}><StudioIcon name="history" />{t("Conversations", "会话历史")}</button>
      <button onClick={newConversation}><StudioIcon name="add" />{t("New conversation", "新建对话")}</button>
    </header>
    <div className="studio-chat-body">
      {history && <SessionBar activeId={conversation} onSelect={id => { setConversation(id); setHistory(false); }} onNew={newConversation} collapsed={false} onToggleCollapse={() => setHistory(false)} locale={locale} showHeader={false} />}
      <div className="studio-chat-content"><ChatView key={generation} locale={locale} conversationId={conversation} onConversationCreated={setConversation} onCardClick={event => {
        const data = event.payload || {};
        if (data.task_id) inspect({ kind: "task", taskId: String(data.task_id) });
        else if (data.trace_id) inspect({ kind: "trace", traceId: String(data.trace_id) });
        else if (event.event_type.startsWith("node.") && data.node_id) inspect({ kind: "node", nodeId: String(data.node_id) });
        else open("operations");
      }} onTraceClick={traceId => inspect({ kind: "trace", traceId })} /></div>
    </div>
  </section>;
}
