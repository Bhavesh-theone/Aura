export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

const TOKEN_KEY = "yuki_os_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

/* ------------------------------ Reachability ------------------------------ */

/**
 * Whether the Aura server answered the last request. Any HTTP response (even a
 * 404) means "up"; only a failed connection means "down". Timeouts leave it
 * unchanged — a slow server is still a server.
 */
export type Reachability = "unknown" | "up" | "down";
let reach: Reachability = "unknown";
const reachListeners = new Set<(r: Reachability) => void>();

function setReach(next: Reachability) {
  if (reach === next) return;
  reach = next;
  reachListeners.forEach((l) => l(next));
}
export function getReachability() {
  return reach;
}
export function onReachability(listener: (r: Reachability) => void) {
  reachListeners.add(listener);
  return () => {
    reachListeners.delete(listener);
  };
}

export const SERVER_DOWN_MESSAGE = `Can’t reach the Aura server at ${API_BASE}.`;

/** Pull the backend's own message out of a FastAPI error body. */
export function messageFromBody(body: unknown): string | null {
  const raw = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
  if (Array.isArray(raw)) {
    return raw
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("; ");
  }
  if (raw !== null && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    if (typeof o.message === "string") return o.message;
    return JSON.stringify(raw);
  }
  return raw !== null && raw !== undefined ? String(raw) : null;
}

/** Tells the auth layer the session is gone; it signs the user out. */
export function notifyAuthExpired() {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("yuki:auth-expired"));
}

export type ApiErrorKind = "network" | "timeout" | "auth" | "forbidden" | "http" | "parse";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status: number | null;
  detail: unknown;
  /** Seconds from a Retry-After header (429), when the server sent one. */
  retryAfter: number | null = null;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }

  /** True only when the backend could not be reached at all. */
  get isUnreachable() {
    return this.kind === "network";
  }
}

/** Map an HTTP failure to a typed ApiError (shared by fetch, XHR and download). */
export function errorForStatus(status: number, body: unknown, sentToken: boolean, fallback?: string): ApiError {
  const msg = messageFromBody(body);
  if (status === 401) {
    // Only an expired/rejected *existing* session bounces the user out. A
    // failed login carries no token and must surface the real reason.
    if (sentToken) {
      notifyAuthExpired();
      return new ApiError("auth", msg || "Your session has expired. Please sign in again.", 401, body);
    }
    return new ApiError("auth", msg || "Invalid credentials.", 401, body);
  }
  if (status === 403) {
    // Signed in but not permitted. Signing out here would be wrong.
    return new ApiError("forbidden", msg || "Your role can’t do that.", 403, body);
  }
  return new ApiError("http", msg || fallback || `Request failed (${status})`, status, body);
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Extra request headers (e.g. Idempotency-Key). */
  headers?: Record<string, string>;
  /** Called with the raw Response of a successful call (to read status/headers). */
  onResponse?: (res: Response) => void;
};

/**
 * Single fetch wrapper: attaches the bearer token, normalises every failure
 * into an ApiError so callers never see a raw TypeError from a dead server.
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal, timeoutMs = 12000, headers: extraHeaders, onResponse } = options;

  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const sentToken = auth && Boolean(headers["Authorization"]);

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  if (signal) signal.addEventListener("abort", () => controller.abort(), { once: true });

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (timedOut) {
      throw new ApiError(
        "timeout",
        `The Aura server did not respond within ${Math.round(timeoutMs / 1000)}s.`,
        null,
        err instanceof Error ? err.message : err,
      );
    }
    setReach("down");
    throw new ApiError("network", SERVER_DOWN_MESSAGE, null, err instanceof Error ? err.message : err);
  } finally {
    clearTimeout(timer);
  }
  setReach("up");

  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      /* non-JSON error body */
    }
    const err = errorForStatus(res.status, detail, sentToken);
    const raw = res.headers.get("Retry-After");
    if (raw && Number.isFinite(Number(raw))) err.retryAfter = Number(raw);
    throw err;
  }
  onResponse?.(res);

  if (res.status === 204) return undefined as T;

  try {
    return (await res.json()) as T;
  } catch (err) {
    throw new ApiError("parse", "The server returned a malformed response.", res.status, err);
  }
}

/** Authenticated file download (the bearer token can't ride on a plain link). */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
  } catch {
    setReach("down");
    throw new ApiError("network", SERVER_DOWN_MESSAGE);
  }
  setReach("up");
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON */
    }
    throw errorForStatus(
      res.status,
      body,
      Boolean(token),
      res.status === 404 ? "That file isn’t available to you — it may sit behind a deal wall." : `Download failed (${res.status})`,
    );
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function checkHealth(): Promise<boolean> {
  try {
    await apiFetch<{ status: string }>("/api/health", { auth: false, timeoutMs: 4000 });
    return true;
  } catch (err) {
    // Any HTTP answer means the server is alive.
    return err instanceof ApiError && err.status !== null;
  }
}
