"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { checkHealth, getReachability, getToken, onReachability, type Reachability } from "./client";
import { eventSocket, type EntityKind, type SocketStatus, type YukiEvent } from "./ws";

/**
 * What the top-bar pill says, and it must be true:
 * - live: the event socket is open, pages refresh the moment something changes;
 * - reconnecting: the server answers but the socket is down, pages poll;
 * - offline: the server itself can't be reached.
 */
export type Connection = "live" | "reconnecting" | "offline";

type EventsState = {
  status: SocketStatus;
  connection: Connection;
  /** Bumped on every inbound event. */
  revision: number;
  last: YukiEvent | null;
  /** True when the socket is not delivering, so pages should poll instead. */
  shouldPoll: boolean;
  /** Bumped when we may have missed events (socket reopened, server came back). */
  resync: number;
};

const EventsContext = createContext<EventsState>({
  status: "idle",
  connection: "reconnecting",
  revision: 0,
  last: null,
  shouldPoll: true,
  resync: 0,
});

/** Polling cadence while the socket is down. */
export const FALLBACK_POLL_MS = 20000;
const HEALTH_RETRY_MS = 5000;

/**
 * Mounted once in the portal layout. Opens THE socket and fans events out
 * through context — no component opens its own connection.
 */
export function EventsProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [reach, setReach] = useState<Reachability>(getReachability());
  const [revision, setRevision] = useState(0);
  const [last, setLast] = useState<YukiEvent | null>(null);
  const [resync, setResync] = useState(0);
  const prevStatus = useRef<SocketStatus>("idle");
  const prevReach = useRef<Reachability>(getReachability());

  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    if (!token) return;
    const offStatus = eventSocket.onStatus((s) => {
      // Reopened after a gap: anything that happened meanwhile was missed.
      if (s === "open" && prevStatus.current !== "open" && prevStatus.current !== "idle") setResync((r) => r + 1);
      prevStatus.current = s;
      setStatus(s);
    });
    const offEvent = eventSocket.onEvent((event) => {
      setLast(event);
      setRevision((r) => r + 1);
    });
    eventSocket.connect(token);
    return () => {
      offStatus();
      offEvent();
      eventSocket.disconnect();
    };
  }, [enabled]);

  useEffect(
    () =>
      onReachability((r) => {
        if (r === "up" && prevReach.current === "down") {
          setResync((n) => n + 1);
          eventSocket.kick();
        }
        prevReach.current = r;
        setReach(r);
      }),
    [],
  );

  // While the server is unreachable, knock on the door every few seconds.
  useEffect(() => {
    if (reach !== "down") return;
    const id = setInterval(() => void checkHealth(), HEALTH_RETRY_MS);
    return () => clearInterval(id);
  }, [reach]);

  const connection: Connection = reach === "down" ? "offline" : status === "open" ? "live" : "reconnecting";

  const value = useMemo<EventsState>(
    () => ({ status, connection, revision, last, shouldPoll: status !== "open", resync }),
    [status, connection, revision, last, resync],
  );

  return <EventsContext.Provider value={value}>{children}</EventsContext.Provider>;
}

export function useEvents() {
  return useContext(EventsContext);
}

/* --------------------------------- Filters -------------------------------- */

export type LiveFilter = (event: YukiEvent) => boolean;

const num = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v !== "" ? Number(v) : null);

/** Any event at all — for cross-cutting views (dashboard, activity). */
export const anyEvent: LiveFilter = () => true;

/** Handoff lifecycle events — the decisions inbox and its badge. */
export const handoffEvents: LiveFilter = (e) => e.type.startsWith("handoff_");

/** Job lifecycle events (a handoff pauses or resumes a job). */
export const jobEvents: LiveFilter = (e) =>
  e.type.startsWith("job_") || e.type.startsWith("handoff_") || (e.type === "entity_changed" && e.payload.kind === "job");

/**
 * Something on this deal changed. `kinds` narrows `entity_changed` to entity
 * kinds (e.g. "document"); an event without a deal_id is treated as possibly
 * relevant. Job/handoff lifecycle events match only when `kinds` is omitted or
 * includes "job" / "handoff".
 */
export function dealEvents(dealId: number, kinds?: EntityKind[]): LiveFilter {
  return (e) => {
    if (e.type === "entity_changed") {
      const d = num(e.payload.deal_id);
      if (d !== null && d !== dealId) return false;
      if (kinds && !kinds.includes(e.payload.kind as EntityKind)) return false;
      return true;
    }
    if (kinds && !kinds.some((k) => e.type.startsWith(`${k}_`))) return false;
    if (e.type.startsWith("handoff_") || e.type.startsWith("job_")) {
      const d = num(e.payload.deal_id);
      return d === null || d === dealId;
    }
    return false;
  };
}

/** Deal list: any change to any deal's headline data (create, stage, flags). */
export const dealListEvents: LiveFilter = (e) => e.type === "entity_changed" && e.payload.kind === "deal";
