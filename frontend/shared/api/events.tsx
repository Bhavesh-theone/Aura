"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getToken } from "./client";
import { eventSocket, type SocketStatus, type YukiEvent } from "./ws";

type EventsState = {
  status: SocketStatus;
  /** Bumped on every inbound event — pages watch this to refetch. */
  revision: number;
  last: YukiEvent | null;
  /** True when the socket is not delivering, so pages should poll instead. */
  shouldPoll: boolean;
};

const EventsContext = createContext<EventsState>({
  status: "idle",
  revision: 0,
  last: null,
  shouldPoll: true,
});

/**
 * Mounted once in the portal layout. Opens THE socket and fans events out
 * through context — no component opens its own connection.
 */
export function EventsProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [revision, setRevision] = useState(0);
  const [last, setLast] = useState<YukiEvent | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    if (!token) return;
    mounted.current = true;
    const offStatus = eventSocket.onStatus(setStatus);
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

  const value = useMemo<EventsState>(
    () => ({ status, revision, last, shouldPoll: status !== "open" }),
    [status, revision, last],
  );

  return <EventsContext.Provider value={value}>{children}</EventsContext.Provider>;
}

export function useEvents() {
  return useContext(EventsContext);
}
