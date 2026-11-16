"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, authApi, type Me, type Organization } from "@/lib/api";

export interface Session {
  me: Me;
  organization: Organization;
}

const SessionContext = createContext<Session | null>(null);

/** The signed-in user, or `null` while it is still loading. */
export function useSession(): Session | null {
  return useContext(SessionContext);
}

/**
 * Loads the signed-in user once in the browser; redirects to /login if the
 * session is gone. Children always render (with `null` session at first), so
 * the page layout appears immediately and fills in when the user arrives.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([authApi.me(), authApi.organization()])
      .then(([me, organization]) => {
        if (!cancelled) setSession({ me, organization });
      })
      .catch((err) => {
        if (cancelled) return;
        // Full page navigation (not router.replace) so the app restarts cleanly
        // from /login instead of keeping this half-loaded layout mounted.
        if (err instanceof ApiError && err.status === 401) window.location.replace("/login");
        else setError("Could not load your session. Is the API running?");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <SessionContext.Provider value={session}>
      {error && (
        <p role="alert" className="bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {children}
    </SessionContext.Provider>
  );
}
