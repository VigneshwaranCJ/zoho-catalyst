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

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join(", ");
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status})`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await rawRequest(path, init);
  if (res.status === 401 && !path.startsWith("/api/v1/auth/")) {
    const refreshed = await rawRequest("/api/v1/auth/refresh", { method: "POST" });
    if (refreshed.ok) res = await rawRequest(path, init);
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const authApi = {
  login: (email: string, password: string) =>
    api<{ user: Me }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
  me: () => api<Me>("/api/v1/auth/me"),
  organization: () => api<Organization>("/api/v1/organization"),
};
