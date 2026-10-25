import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, captureRuntimeConnection } from "../../lib/api";
import { parseStudioUIView, type StudioUIView } from "../../lib/studioExtensions";
import type { OperationsSnapshot } from "../OperationsConsole";

export type StudioHealth = { running?: boolean; platform?: string; architecture?: string; kernel?: { configured?: boolean; connected?: boolean; ready?: boolean; state?: string } };
type Read<T> = { data: T | null; loading: boolean; error: string; receivedAt: number | null };
type Source = "operations" | "health" | "extensions";
type Snapshot = Read<OperationsSnapshot> & { health: Read<StudioHealth>; extensions: Read<StudioUIView>; invalidateExtensions: () => void; refresh: (sources?: readonly Source[]) => void; subscribeLive: (active: () => boolean, sources: readonly Source[]) => () => void };
const empty = { data: null, loading: true, error: "", receivedAt: null };
const Context = createContext<Snapshot>({ ...empty, health: empty, extensions: empty, invalidateExtensions: () => {}, refresh: () => {}, subscribeLive: () => () => {} });
export const useStudioSnapshot = () => useContext(Context);

/** Transient reads of existing APIs, shared by all panels. No Runtime state owner. */
export function StudioSnapshot({ children }: { children: React.ReactNode }) {
  const [operations, setOperations] = useState<Read<OperationsSnapshot>>(empty);
  const [health, setHealth] = useState<Read<StudioHealth>>(empty);
  const [extensions, setExtensions] = useState<Read<StudioUIView>>(empty);
  const [guard] = useState(captureRuntimeConnection);
  const alive = useRef(false);
  const flights = useRef(new Map<Source, AbortController>());
  const received = useRef<Partial<Record<Source, number>>>({});
  const readers = useRef(new Set<{ active: () => boolean; sources: readonly Source[] }>());
  const refresh = useCallback((sources: readonly Source[] = ["operations", "health", "extensions"]) => {
    if (!alive.current) return;
    for (const source of new Set(sources)) {
      if (flights.current.has(source)) continue;
      const abort = new AbortController(); flights.current.set(source, abort);
      const current = () => { guard(); return alive.current && flights.current.get(source) === abort; };
      const read = async () => {
        try {
          guard();
          const loading = <T,>(value: Read<T>) => ({ ...value, loading: true, error: "" });
          if (source === "operations") setOperations(loading); else if (source === "health") setHealth(loading); else setExtensions(loading);
          const path = source === "operations" ? "/api/v1/control/operations" : source === "health" ? "/api/v1/health/detailed" : "/api/v1/studio/extensions";
          const raw = await api<unknown>(path, { signal: abort.signal });
          if (!current()) return;
          const receivedAt = Date.now(); received.current[source] = receivedAt;
          if (source === "operations") setOperations({ data: raw as OperationsSnapshot, loading: false, error: "", receivedAt });
          else if (source === "health") setHealth({ data: raw as StudioHealth, loading: false, error: "", receivedAt });
          else setExtensions({ data: parseStudioUIView(raw), loading: false, error: "", receivedAt });
        } catch (error) {
          // A superseded read cannot restore disabled extensions or old Controller data.
          if (alive.current && flights.current.get(source) === abort) {
            const failed = { data: null, loading: false, error: error instanceof Error ? error.message : "Runtime unavailable.", receivedAt: null };
            if (source === "operations") setOperations(failed); else if (source === "health") setHealth(failed); else setExtensions(failed);
          }
        } finally { if (flights.current.get(source) === abort) flights.current.delete(source); }
      };
      void read();
    }
  }, [guard]);
  const invalidateExtensions = useCallback(() => {
    flights.current.get("extensions")?.abort(); flights.current.delete("extensions");
    delete received.current.extensions; setExtensions(empty); refresh(["extensions"]);
  }, [refresh]);
  const subscribeLive = useCallback((active: () => boolean, sources: readonly Source[]) => {
    const reader = { active, sources }; readers.current.add(reader);
    const frame = requestAnimationFrame(() => {
      if (readers.current.has(reader) && active()) refresh(sources.filter(source => Date.now() - (received.current[source] || 0) >= 5000));
    });
    return () => { cancelAnimationFrame(frame); readers.current.delete(reader); };
  }, [refresh]);
  useEffect(() => {
    alive.current = true; refresh(["operations", "extensions"]);
    const poll = () => {
      if (document.visibilityState === "hidden") return;
      const sources = new Set<Source>();
      for (const reader of readers.current) { try { if (reader.active()) reader.sources.forEach(source => sources.add(source)); } catch { /* Retired presentations contribute no subscriptions. */ } }
      if (sources.size) refresh([...sources]);
    };
    const timer = window.setInterval(poll, 5000);
    document.addEventListener("visibilitychange", poll);
    const pending = flights.current;
    return () => { alive.current = false; window.clearInterval(timer); document.removeEventListener("visibilitychange", poll); for (const abort of pending.values()) abort.abort(); pending.clear(); };
  }, [refresh]);
  const value = useMemo(() => ({ ...operations, health, extensions, invalidateExtensions, refresh, subscribeLive }), [operations, health, extensions, invalidateExtensions, refresh, subscribeLive]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
