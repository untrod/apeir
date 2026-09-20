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
import { fetchEventStream, type RuntimeEventEnvelope } from "../lib/api";
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
  private stopped = false;

  start(config?: Partial<EventClientConfig>): void {
    if (config) this.config = { ...this.config, ...config };
    this.stopped = false;
    this.reconnectAttempt = 0;

    if (this.config.mode === "websocket") {
      this.connectWebSocket();
    } else {
      this.startPolling();
    }
  }

  stop(): void {
    this.stopped = true;
    if (this.ws) { this.ws.close(); this.ws = null; }
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.pollTimer) { clearTimeout(this.pollTimer); this.pollTimer = null; }
  }

  // WebSocket

  private connectWebSocket(): void {
    if (this.stopped) return;
    const wsUrl = this.config.baseUrl.replace(/^http/, "ws") + "/api/v1/events/ws";
    try {
      this.ws = new WebSocket(wsUrl);
      this.ws.onopen = () => {
        this.reconnectAttempt = 0;
        this.backfill();
      };
      this.ws.onmessage = (evt) => {
        try {
          const event: RuntimeEventEnvelope = JSON.parse(evt.data);
          entityStore.ingestEvent(event);
        } catch { /* skip malformed */ }
      };
      this.ws.onclose = () => {
        this.ws = null;
        this.scheduleReconnect();
      };
      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = Math.min(
      WS_RECONNECT_MAX_MS,
      WS_RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempt),
    );
    this.reconnectAttempt++;
    this.reconnectTimer = setTimeout(() => this.connectWebSocket(), delay);
  }

  // Polling fallback

  private startPolling(): void {
    if (this.stopped) return;
    this.backfill().then(() => {
      this.pollLoop();
    });
  }

  private pollLoop(): void {
    if (this.stopped) return;
    const domain = this.config.domains?.[0] || "";
    const cursor = entityStore.getState().cursors[domain] || 0;
    fetchEventStream(domain, String(cursor), BACKFILL_BATCH_SIZE)
      .then((result) => {
        if (result?.events) {
          for (const event of result.events) {
            entityStore.ingestEvent(event);
          }
        }
      })
      .catch(() => { /* retry next poll */ })
      .finally(() => {
        if (!this.stopped) {
          this.pollTimer = setTimeout(() => this.pollLoop(), POLL_INTERVAL_MS);
        }
      });
  }

  // Backfill

  private async backfill(): Promise<void> {
    const state = entityStore.getState();
    for (const [domain, cursor] of Object.entries(state.cursors)) {
      try {
        let afterSeq = cursor;
        let batch: { events: RuntimeEventEnvelope[] } | null;
        do {
          batch = await fetchEventStream(domain, String(afterSeq), BACKFILL_BATCH_SIZE);
          if (batch?.events) {
            for (const event of batch.events) {
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
