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
import { captureRuntimeConnection, fetchEventStream, type RuntimeEventEnvelope } from "../lib/api";
import type { SequenceNumber } from "./types";


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

  start(config?: Partial<EventClientConfig>): void {
    this.stop();
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
    const cursor = entityStore.getState().cursors[domain] || 0;
    fetchEventStream(domain, String(cursor), BACKFILL_BATCH_SIZE)
      .then((result) => {
        if (!current()) return;
        if (result?.events) {
          for (const event of result.events) {
            if (!current()) return;
            entityStore.ingestEvent(event);
          }
        }
      })
      .catch(() => { /* retry next poll */ })
      .finally(() => {
        if (current()) {
          this.pollTimer = setTimeout(() => this.pollLoop(current), POLL_INTERVAL_MS);
        }
      });
  }

  // Backfill

  private async backfill(current: () => boolean): Promise<void> {
    const state = entityStore.getState();
    for (const [domain, cursor] of Object.entries(state.cursors)) {
      try {
        let afterSeq = cursor;
        let batch: { events: RuntimeEventEnvelope[] } | null;
        do {
          if (!current()) return;
          batch = await fetchEventStream(domain, String(afterSeq), BACKFILL_BATCH_SIZE);
          if (!current()) return;
          if (batch?.events) {
            for (const event of batch.events) {
              if (!current()) return;
              entityStore.ingestEvent(event);
            }
            if (batch.events.length > 0) {
              afterSeq = batch.events[batch.events.length - 1].sequence;
            }
          }
        } while (batch?.events && batch.events.length === BACKFILL_BATCH_SIZE);
      } catch {
        // Domain backfill failed — will retry on next reconnect
      }
    }
  }
}


// Singleton export


export const eventClient = new EventClientImpl();
