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

export type ApiErrorKind = "network" | "timeout" | "auth" | "forbidden" | "http" | "parse";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status: number | null;
  detail: unknown;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }

  /**
   * True only when the backend could not be reached at all — a genuinely dead
   * server. Deliberately excludes "timeout": a slow-but-alive API must never
   * cause callers to substitute sample data for the live queue.
   */
  get isUnreachable() {
    return this.kind === "network";
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
};

/**
 * Single fetch wrapper: attaches the bearer token, normalises every failure
 * into an ApiError so callers never see a raw TypeError from a dead server.
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal, timeoutMs = 12000 } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
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
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    // A timeout means the server is alive but slow — on CPU-only inference that
    // is normal. It must NOT be reported as unreachable, or callers swap in
    // sample data and render fabricated approvals as if they were live.
    if (timedOut) {
      throw new ApiError(
        "timeout",
        `The API did not respond within ${Math.round(timeoutMs / 1000)}s.`,
        null,
        err instanceof Error ? err.message : err,
      );
    }
    throw new ApiError(
      "network",
      `Cannot reach the Yuki OS API at ${API_BASE}`,
      null,
      err instanceof Error ? err.message : err,
    );
  } finally {
    clearTimeout(timer);
  }

  // Read the body first so the backend's own message ("Invalid credentials")
  // survives, rather than being overwritten by a generic session-expiry string.
  let detail: unknown = null;
  if (!res.ok) {
    try {
      detail = await res.json();
    } catch {
      /* non-JSON error body */
    }
  }
  const detailMessage =
    detail && typeof detail === "object" && "detail" in detail
      ? String((detail as { detail: unknown }).detail)
      : null;

  if (res.status === 401) {
    // Only an expired/rejected *existing* session should bounce the user out.
    // A failed login carries no token and must surface the real reason.
    if (sentToken) {
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("yuki:auth-expired"));
      }
      throw new ApiError(
        "auth",
        detailMessage || "Your session has expired. Please sign in again.",
        401,
        detail,
      );
    }
    throw new ApiError("auth", detailMessage || "Invalid credentials.", 401, detail);
  }

  if (res.status === 403) {
    // Authenticated but not permitted (e.g. non-admin deciding an approval).
    // Signing the user out here would be wrong — they are correctly signed in.
    throw new ApiError(
      "forbidden",
      detailMessage || "You do not have permission to do that.",
      403,
      detail,
    );
  }

  if (!res.ok) {
    throw new ApiError("http", detailMessage || `Request failed (${res.status})`, res.status, detail);
  }

  if (res.status === 204) return undefined as T;

  try {
    return (await res.json()) as T;
  } catch (err) {
    throw new ApiError("parse", "The API returned a malformed response.", res.status, err);
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    await apiFetch<{ status: string }>("/api/health", { auth: false, timeoutMs: 4000 });
    return true;
  } catch {
    return false;
  }
}
