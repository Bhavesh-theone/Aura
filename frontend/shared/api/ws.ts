import { API_BASE } from "./client";

/** Every event type the backend publishes (core/services/*, core/services/notifying_audit.py). */
export type EventType =
  | "job_submitted"
  | "job_complete"
  | "job_failed"
  | "handoff_created"
  | "handoff_resolved"
  | "handoff_escalated"
  | "entity_changed";

/** core/policy/entity_policy.py ENTITY_KINDS. */
export const ENTITY_KINDS = ["deal", "document", "diligence", "condition", "handoff", "job", "finding", "extraction", "signoff"] as const;
export type EntityKind = (typeof ENTITY_KINDS)[number];

export type JobEventPayload = { job_id: number; deal_id: number | null };
export type HandoffEventPayload = { handoff_id: number; job_id: number | null; deal_id: number | null; approved?: boolean };
export type EntityChangedPayload = { kind: EntityKind; deal_id: number | null };

export type YukiEvent = { type: EventType; payload: Record<string, unknown> };

export type SocketStatus = "idle" | "connecting" | "open" | "closed";

type EventListener = (event: YukiEvent) => void;
type StatusListener = (status: SocketStatus) => void;

function wsUrl(token: string) {
  // Honour an explicit WS base when set (e.g. a different host or a TLS
  // terminator); otherwise derive it from the API base.
  const base =
    process.env.NEXT_PUBLIC_WS_BASE?.replace(/\/$/, "") || API_BASE.replace(/^http/, "ws");
  return `${base}/ws/events?token=${encodeURIComponent(token)}`;
}

/**
 * ONE socket for the whole portal. Opened by the portal layout, fanned out to
 * every page through the EventsProvider. Reconnects with backoff; consumers
 * poll whenever `status !== "open"`.
 */
class EventSocket {
  private socket: WebSocket | null = null;
  private token: string | null = null;
  private listeners = new Set<EventListener>();
  private statusListeners = new Set<StatusListener>();
  private retries = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;

  status: SocketStatus = "idle";

  connect(token: string) {
    if (typeof window === "undefined") return;
    if (this.socket && this.token === token) return;

    // A different token means a different session. Tear the old socket down
    // first — otherwise it is orphaned but still live, delivering events for
    // the previous user and racing its own reconnect timer against this one.
    if (this.socket) this.teardown();

    this.token = token;
    this.stopped = false;
    this.open();
  }

  /** Reconnect now (e.g. the server just came back) instead of waiting out the backoff. */
  kick() {
    if (this.stopped || this.status === "open" || this.status === "connecting") return;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.retries = 0;
    this.open();
  }

  /** Close the current socket without triggering a reconnect. */
  private teardown() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.retries = 0;
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      try {
        this.socket.close();
      } catch {
        /* already closing */
      }
      this.socket = null;
    }
  }

  private setStatus(next: SocketStatus) {
    if (this.status === next) return;
    this.status = next;
    this.statusListeners.forEach((l) => l(next));
  }

  private open() {
    if (this.stopped || !this.token) return;
    this.setStatus("connecting");
    let socket: WebSocket;
    try {
      socket = new WebSocket(wsUrl(this.token));
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.retries = 0;
      this.setStatus("open");
    };

    socket.onmessage = (raw) => {
      let parsed: YukiEvent | null = null;
      try {
        const data = JSON.parse(String(raw.data));
        if (data && typeof data.type === "string") {
          parsed = { type: data.type, payload: data.payload ?? {} };
        }
      } catch {
        return;
      }
      if (parsed) this.listeners.forEach((l) => l(parsed as YukiEvent));
    };

    socket.onerror = () => {
      try {
        socket.close();
      } catch {
        /* already closing */
      }
    };

    socket.onclose = () => {
      this.socket = null;
      this.setStatus("closed");
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.stopped) return;
    if (this.timer) clearTimeout(this.timer);
    const delay = Math.min(1000 * 2 ** this.retries, 20000);
    this.retries += 1;
    this.timer = setTimeout(() => this.open(), delay);
  }

  disconnect() {
    this.stopped = true;
    this.token = null;
    this.retries = 0;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.socket) {
      this.socket.onclose = null;
      try {
        this.socket.close();
      } catch {
        /* ignore */
      }
      this.socket = null;
    }
    this.setStatus("idle");
  }

  onEvent(listener: EventListener) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  onStatus(listener: StatusListener) {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => {
      this.statusListeners.delete(listener);
    };
  }
}

export const eventSocket = new EventSocket();
