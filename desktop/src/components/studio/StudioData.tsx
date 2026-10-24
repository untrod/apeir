import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, captureRuntimeConnection } from "../../lib/api";
import type { OperationsSnapshot } from "../OperationsConsole";

export type StudioHealth = { running?: boolean; platform?: string; architecture?: string; kernel?: { configured?: boolean; connected?: boolean; ready?: boolean; state?: string } };
type Read<T> = { data: T | null; loading: boolean; error: string; receivedAt: number | null };
type Source = "operations" | "health";
type Snapshot = Read<OperationsSnapshot> & { health: Read<StudioHealth>; refresh: (sources?: readonly Source[]) => void; subscribeLive: (active: () => boolean, sources: readonly Source[]) => () => void };
const empty = { data: null, loading: true, error: "", receivedAt: null };
const Context = createContext<Snapshot>({ ...empty, health: empty, refresh: () => {}, subscribeLive: () => () => {} });
export const useStudioSnapshot = () => useContext(Context);

/** Transient reads of existing APIs, shared by all panels. No Runtime state owner. */
export function StudioSnapshot({ children }: { children: React.ReactNode }) {
  const [operations, setOperations] = useState<Read<OperationsSnapshot>>(empty);
  const [health, setHealth] = useState<Read<StudioHealth>>(empty);
  const [guard] = useState(captureRuntimeConnection);
  const alive = useRef(false);
  const flights = useRef(new Set<Source>());
  const received = useRef<Partial<Record<Source, number>>>({});
  const aborts = useRef(new Set<AbortController>());
  const readers = useRef(new Set<{ active: () => boolean; sources: readonly Source[] }>());
  const refresh = useCallback((sources: readonly Source[] = ["operations", "health"]) => {
    if (!alive.current) return;
    for (const source of new Set(sources)) {
      if (flights.current.has(source)) continue;
      const abort = new AbortController(); aborts.current.add(abort); flights.current.add(source);
      const read = async () => {
        try {
          guard();
          if (source === "operations") {
            setOperations(value => ({ ...value, loading: true, error: "" }));
            const data = await api<OperationsSnapshot>("/api/v1/control/operations", { signal: abort.signal });
            guard(); if (alive.current) { received.current[source] = Date.now(); setOperations({ data, loading: false, error: "", receivedAt: received.current[source]! }); }
          } else {
            setHealth(value => ({ ...value, loading: true, error: "" }));
            const data = await api<StudioHealth>("/api/v1/health/detailed", { signal: abort.signal });
            guard(); if (alive.current) { received.current[source] = Date.now(); setHealth({ data, loading: false, error: "", receivedAt: received.current[source]! }); }
          }
        } catch (error) {
          if (alive.current) {
            const failed = { data: null, loading: false, error: error instanceof Error ? error.message : "Runtime unavailable.", receivedAt: null };
            if (source === "operations") setOperations(failed); else setHealth(failed);
          }
        } finally { flights.current.delete(source); aborts.current.delete(abort); }
      };
      void read();
    }
  }, [guard]);
  const subscribeLive = useCallback((active: () => boolean, sources: readonly Source[]) => {
    const reader = { active, sources }; readers.current.add(reader);
    const frame = requestAnimationFrame(() => {
      if (readers.current.has(reader) && active()) refresh(sources.filter(source => Date.now() - (received.current[source] || 0) >= 5000));
    });
    return () => { cancelAnimationFrame(frame); readers.current.delete(reader); };
  }, [refresh]);
  useEffect(() => {
    alive.current = true; refresh(["operations"]);
    const poll = () => {
      if (document.visibilityState === "hidden") return;
      const sources = new Set<Source>();
      for (const reader of readers.current) { try { if (reader.active()) reader.sources.forEach(source => sources.add(source)); } catch { /* A retired presentation contributes no subscriptions. */ } }
      if (sources.size) refresh([...sources]);
    };
    const timer = window.setInterval(poll, 5000);
    document.addEventListener("visibilitychange", poll);
    const pending = aborts.current;
    return () => { alive.current = false; window.clearInterval(timer); document.removeEventListener("visibilitychange", poll); for (const abort of pending) abort.abort(); };
  }, [refresh]);
  const value = useMemo(() => ({ ...operations, health, refresh, subscribeLive }), [operations, health, refresh, subscribeLive]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
