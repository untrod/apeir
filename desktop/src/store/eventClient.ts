/**
 * EventClient — Persistent connection to Nous Runtime Event stream.
 *
 * Uses WebSocket (primary) with SSE/polling fallback.
 * Features:
 *   - Auto-reconnect with exponential backoff (1s → 30s max)
 *   - Backfill: on reconnect, fetches missed events via REST cursor
 *   - Dedup: passes events through entityStore.ingestEvent()
 *   - Domain filtering: subscribe to specific event domains
 */

import { entityStore } from "./entityStore";
import { ApiError, captureRuntimeConnection, fetchEventStream, type RuntimeEventEnvelope } from "../lib/api";


// Configuration


const WS_RECONNECT_BASE_MS = 1000;
const WS_RECONNECT_MAX_MS = 30000;
const POLL_INTERVAL_MS = 2000;
const BACKFILL_BATCH_SIZE = 200;

type ConnectionMode = "websocket" | "polling";

interface EventClientConfig {
  baseUrl: string;
  mode?: ConnectionMode;
  domains?: string[];
  onError?: () => void;
}


// WebSocket connection


class EventClientImpl {
  private ws: WebSocket | null = null;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private config: EventClientConfig = { baseUrl: "ws://localhost:8770", mode: "polling" };
  private stopped = true;
  private generation = 0;
  private connection?: () => void;
  private eventCursors = new Map<string, string>();

  start(config?: Partial<EventClientConfig>): void {
    this.stop();
    try { this.connection?.(); } catch { this.eventCursors.clear(); }
    this.connection = captureRuntimeConnection();
    if (config) this.config = { ...this.config, ...config };
    this.stopped = false;
    this.reconnectAttempt = 0;
    const generation = this.generation;
    const connection = captureRuntimeConnection();
    const current = () => {
      if (this.stopped || this.generation !== generation) return false;
      try { connection(); return true; } catch { this.stop(); return false; }
    };

    if (this.config.mode === "websocket") {
      this.connectWebSocket(current);
    } else {
      this.startPolling(current);
    }
  }

  stop(): void {
    this.stopped = true;
    this.generation++;
    if (this.ws) { this.ws.close(); this.ws = null; }
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.pollTimer) { clearTimeout(this.pollTimer); this.pollTimer = null; }
  }

  // WebSocket

  private connectWebSocket(current: () => boolean): void {
    if (!current()) return;
    const wsUrl = this.config.baseUrl.replace(/^http/, "ws") + "/api/v1/events/ws";
    try {
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      ws.onopen = () => {
        if (!current() || this.ws !== ws) return;
        this.reconnectAttempt = 0;
        void this.backfill(current);
      };
      ws.onmessage = (evt) => {
        if (!current() || this.ws !== ws) return;
        try {
          const event: RuntimeEventEnvelope = JSON.parse(evt.data);
          entityStore.ingestEvent(event);
        } catch { /* skip malformed */ }
      };
      ws.onclose = () => {
        if (!current() || this.ws !== ws) return;
        this.ws = null;
        this.scheduleReconnect(current);
      };
      ws.onerror = () => {
        if (current() && this.ws === ws) ws.close();
      };
    } catch {
      this.scheduleReconnect(current);
    }
  }

  private scheduleReconnect(current: () => boolean): void {
    if (!current()) return;
    const delay = Math.min(
      WS_RECONNECT_MAX_MS,
      WS_RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempt),
    );
    this.reconnectAttempt++;
    this.reconnectTimer = setTimeout(() => this.connectWebSocket(current), delay);
  }

  // Polling fallback

  private startPolling(current: () => boolean): void {
    if (!current()) return;
    this.backfill(current).then(() => {
      if (current()) this.pollLoop(current);
    });
  }

  private pollLoop(current: () => boolean): void {
    if (!current()) return;
    const domain = this.config.domains?.[0] || "";
    this.readPage(domain, current)
      .catch(error => this.handleReadFailure(error, current))
      .finally(() => {
        if (current()) this.pollTimer = setTimeout(() => this.pollLoop(current), POLL_INTERVAL_MS);
      });
  }

  private async readPage(domain: string, current: () => boolean): Promise<boolean> {
    if (!current()) return false;
    const afterId = this.eventCursors.get(domain) || "";
    const result = await fetchEventStream(domain, afterId, BACKFILL_BATCH_SIZE);
    if (!current()) return false;
    const ids = result.events.map(event => event.event_id);
    if (ids.some(id => typeof id !== "string" || !id || id === afterId) || new Set(ids).size !== ids.length) {
      throw new ApiError("NOUS_EVENT_STREAM_INVALID", "Event history did not advance; reload current state");
    }
    for (const event of result.events) {
      if (!current()) return false;
      entityStore.ingestEvent(event);
    }
    if (!current()) return false;
    if (ids.length) this.eventCursors.set(domain, ids[ids.length - 1]);
    return result.events.length === BACKFILL_BATCH_SIZE;
  }

  private handleReadFailure(error: unknown, current: () => boolean): void {
    if (!current()) return;
    if (error instanceof ApiError && ["NOUS_EVENT_CURSOR_UNAVAILABLE", "NOUS_EVENT_STREAM_INVALID", "NOUS_EVENT_STREAM_UNAVAILABLE"].includes(error.code)) {
      this.stop();
      this.config.onError?.();
    }
    // Transient read failures retain the original cursor and bounded polling.
  }

  private async backfill(current: () => boolean): Promise<void> {
    const domain = this.config.domains?.[0] || "";
    try {
      while (current() && await this.readPage(domain, current)) { /* Drain bounded pages by event ID. */ }
    } catch (error) {
      this.handleReadFailure(error, current);
    }
  }

}


// Singleton export


export const eventClient = new EventClientImpl();
