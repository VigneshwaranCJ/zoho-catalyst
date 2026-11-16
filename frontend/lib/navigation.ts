/**
 * Turn an untrusted `?next=` value into a safe same-origin path.
 *
 * String checks like `startsWith("/")` are not enough: browsers treat
 * `/\evil.com` and `//evil.com` as links to another site. Parsing with the URL
 * API and comparing origins handles every such trick.
 */
export function safeNextPath(next: string | null, origin: string, fallback = "/dashboard"): string {
  if (!next) return fallback;
  try {
    const url = new URL(next, origin);
    if (url.origin !== origin) return fallback;
    if (url.pathname === "/login") return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
