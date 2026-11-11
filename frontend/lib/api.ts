// Small typed client for the FastAPI backend.
//
// * Requests go to same-origin `/api/...` (proxied by next.config.ts rewrites).
// * Cookies carry the session; JS never sees the access/refresh tokens.
// * State-changing requests send the CSRF token from the readable `csp_csrf` cookie.
// * On 401 we try one silent refresh, then retry once.

export type Permission =
  | "org:manage"
  | "knowledge:edit"
  | "knowledge:publish"
  | "conversations:view"
  | "tickets:handle"
  | "agent:approve"
  | "analytics:view";

export interface Me {
  user_id: string;
  organization_id: string;
  email: string;
  display_name: string;
  role: "org_admin" | "editor" | "agent" | "viewer";
  permissions: Permission[];
}

export interface Organization {
  id: string;
  slug: string;
  name: string;
  status: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** Raw `detail` from FastAPI, for errors that carry data (e.g. org choices). */
    public detail?: unknown,
  ) {
    super(message);
  }
}

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${name}=`))
    ?.split("=")[1];
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

async function rawRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie("csp_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  return fetch(path, { ...init, method, headers, credentials: "same-origin" });
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = (await res.json()).detail;
  } catch {
    /* not JSON */
  }
  let message = `Request failed (${res.status})`;
  if (typeof detail === "string") message = detail;
  else if (Array.isArray(detail)) message = detail.map((d: { msg: string }) => d.msg).join(", ");
  else if (detail && typeof detail === "object" && "message" in detail) {
    message = String((detail as { message: unknown }).message);
  }
  return new ApiError(res.status, message, detail);
}

const NO_REFRESH_PATHS = new Set([
  "/api/v1/auth/login",
  "/api/v1/auth/refresh",
  "/api/v1/auth/logout",
]);

// Single-flight refresh: when several calls get 401 at the same moment they all
// wait for ONE refresh request. Parallel refreshes with the same token would be
// rejected by the server (rotation allows each refresh token to be used once).
let refreshInFlight: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  refreshInFlight ??= rawRequest("/api/v1/auth/refresh", { method: "POST" })
    // 409 = another tab refreshed a moment ago; its new cookies are already set.
    .then((res) => res.ok || res.status === 409)
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await rawRequest(path, init);
  // Refresh on 401 for every call except the endpoints that manage the session
  // themselves (refreshing on a failed login/refresh would loop or be pointless).
  if (res.status === 401 && !NO_REFRESH_PATHS.has(path)) {
    if (await refreshSession()) res = await rawRequest(path, init);
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const authApi = {
  login: (email: string, password: string, organizationSlug?: string) =>
    api<{ user: Me }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, organization_slug: organizationSlug }),
    }),
  logout: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
  me: () => api<Me>("/api/v1/auth/me"),
  organization: () => api<Organization>("/api/v1/organization"),
};
