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
  // JSON bodies get a JSON content type; FormData (file uploads) must set its own
  // multipart boundary, so we leave its Content-Type alone.
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
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

/** Send a request; on 401 refresh the session once and retry. Throws ApiError if not ok. */
async function send(path: string, init: RequestInit): Promise<Response> {
  let res = await rawRequest(path, init);
  // Refresh on 401 for every call except the endpoints that manage the session
  // themselves (refreshing on a failed login/refresh would loop or be pointless).
  if (res.status === 401 && !NO_REFRESH_PATHS.has(path)) {
    if (await refreshSession()) res = await rawRequest(path, init);
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiText(path: string, init: RequestInit = {}): Promise<string> {
  return (await send(path, init)).text();
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

// ------------------------------------------------------------------ knowledge

export type JobStatus =
  | "queued"
  | "fetching"
  | "extracting"
  | "extracted"
  | "generating"
  | "needs_review"
  | "reviewed"
  | "failed";

export interface IngestionJob {
  id: string;
  status: JobStatus;
  progress: number;
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface KnowledgeSource {
  id: string;
  name: string;
  source_type: "pdf" | "docx" | "html" | "markdown" | "text" | "url";
  uri: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  page_count: number | null;
  created_at: string;
  job: IngestionJob | null;
}

export interface KnowledgeSourceDetail extends KnowledgeSource {
  sha256: string | null;
  outline: { text: string; page: number | null }[];
  stats: Record<string, unknown>;
}

export interface UploadItem {
  filename: string;
  status: "created" | "duplicate" | "rejected";
  error: string | null;
  source: KnowledgeSource | null;
}

export const ACTIVE_JOB_STATUSES: JobStatus[] = ["queued", "fetching", "extracting", "generating"];

export const knowledgeApi = {
  list: () => api<KnowledgeSource[]>("/api/v1/knowledge/sources"),
  get: (id: string) => api<KnowledgeSourceDetail>(`/api/v1/knowledge/sources/${encodeURIComponent(id)}`),
  extracted: (id: string) => apiText(`/api/v1/knowledge/sources/${encodeURIComponent(id)}/extracted`),
  upload: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return api<{ items: UploadItem[] }>("/api/v1/knowledge/sources", { method: "POST", body: form });
  },
  addUrl: (url: string) =>
    api<KnowledgeSource>("/api/v1/knowledge/sources/url", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  retry: (id: string) =>
    api<KnowledgeSource>(`/api/v1/knowledge/sources/${encodeURIComponent(id)}/retry`, { method: "POST" }),
  remove: (id: string) =>
    api<void>(`/api/v1/knowledge/sources/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

// ------------------------------------------------------------------ OKF knowledge documents

export interface ValidationIssue {
  level: "error" | "warning";
  path: string;
  message: string;
}

export interface DraftItem {
  version_id: string;
  document_id: string;
  path: string;
  title: string;
  doc_type: string;
  audience: string;
  version_no: number;
  is_update: boolean;
  source_id: string | null;
  source_name: string | null;
  job_id: string | null;
  created_at: string;
  error_count: number;
  warning_count: number;
  has_injection_warnings: boolean;
}

export interface VersionDetail {
  version_id: string;
  document_id: string;
  path: string;
  title: string;
  doc_type: string;
  version_no: number;
  review_status: "pending" | "approved" | "rejected" | "superseded";
  content: string;
  validation: { ok: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[] };
  diff: string;
  has_injection_warnings: boolean;
  generated_by: string;
  created_at: string;
  reviewed_at: string | null;
  review_note: string | null;
  git_commit_sha: string | null;
}

export interface KnowledgeDocumentItem {
  id: string;
  path: string;
  title: string;
  doc_type: string;
  description: string | null;
  audience: string;
  status: "draft" | "live" | "archived";
  tags: string[];
  current_version_no: number | null;
  pending_drafts: number;
  updated_at: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocumentItem {
  content: string | null;
  trust_tier: string | null;
  versions: {
    version_id: string;
    version_no: number;
    review_status: string;
    generated_by: string;
    created_at: string;
    reviewed_at: string | null;
    git_commit_sha: string | null;
  }[];
}

export interface SearchHit {
  section_id: string;
  document_id: string;
  path: string;
  doc_title: string;
  doc_type: string;
  heading: string;
  anchor: string;
  heading_path: string[];
  snippet: string;
  source_pages: number[];
  score: number;
}

const enc = encodeURIComponent;

export const knowledgeDocsApi = {
  reviews: () => api<DraftItem[]>("/api/v1/knowledge/reviews"),
  version: (id: string) => api<VersionDetail>(`/api/v1/knowledge/versions/${enc(id)}`),
  approve: (versionIds: string[], note: string | null, acknowledgeWarnings: boolean) =>
    api<{ commit_sha: string; approved: number }>("/api/v1/knowledge/versions/approve", {
      method: "POST",
      body: JSON.stringify({ version_ids: versionIds, note, acknowledge_warnings: acknowledgeWarnings }),
    }),
  reject: (id: string, note: string | null) =>
    api<void>(`/api/v1/knowledge/versions/${enc(id)}/reject`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  documents: () => api<KnowledgeDocumentItem[]>("/api/v1/knowledge/documents"),
  document: (id: string) => api<KnowledgeDocumentDetail>(`/api/v1/knowledge/documents/${enc(id)}`),
  edit: (id: string, content: string) =>
    api<VersionDetail>(`/api/v1/knowledge/documents/${enc(id)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  archive: (id: string) => api<void>(`/api/v1/knowledge/documents/${enc(id)}`, { method: "DELETE" }),
  search: (q: string) =>
    api<{ query: string; hits: SearchHit[] }>(`/api/v1/knowledge/search?q=${enc(q)}&limit=10`),
  generate: (sourceId: string) =>
    api<KnowledgeSource>(`/api/v1/knowledge/sources/${enc(sourceId)}/generate`, { method: "POST" }),
};
