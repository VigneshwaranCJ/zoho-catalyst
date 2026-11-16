import type { ReactNode } from "react";

import { DashboardShell } from "./shell";

// Server component wrapper: the shell (sidebar + session loading) is a client
// component. Pages render immediately with skeletons and fill in once the
// browser has loaded the signed-in user from FastAPI.
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <DashboardShell>{children}</DashboardShell>;
}
