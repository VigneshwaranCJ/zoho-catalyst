"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import {
  BarChart3,
  BookOpen,
  Bot,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Settings,
  Ticket,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { authApi } from "@/lib/api";
import { cn } from "@/lib/utils";

import { SessionProvider, useSession } from "./session";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, phase: null },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen, phase: null },
  { href: "/conversations", label: "Conversations", icon: MessagesSquare, phase: 7 },
  { href: "/tickets", label: "Tickets", icon: Ticket, phase: 7 },
  { href: "/analytics", label: "Analytics", icon: BarChart3, phase: 8 },
  { href: "/settings", label: "Settings", icon: Settings, phase: 8 },
] as const;

/** Navigation links; `pathname` highlights the current section (null = none yet). */
function NavList({ pathname }: { pathname: string | null }) {
  return (
    <nav className="flex-1 space-y-1 p-2" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon, phase }) => {
        const active = pathname !== null && (pathname === href || pathname.startsWith(`${href}/`));
        const disabled = phase !== null;
        const classes = cn(
          "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
          active && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
          disabled ? "cursor-not-allowed text-muted-foreground" : "hover:bg-sidebar-accent",
        );
        const content = (
          <>
            <Icon className="size-4" aria-hidden />
            <span className="flex-1">{label}</span>
            {disabled && (
              <Badge variant="outline" className="text-[10px]">
                Phase {phase}
              </Badge>
            )}
          </>
        );
        return disabled ? (
          <span key={href} className={classes} aria-disabled="true">
            {content}
          </span>
        ) : (
          <Link key={href} href={href} className={classes} aria-current={active ? "page" : undefined}>
            {content}
          </Link>
        );
      })}
    </nav>
  );
}

function ActiveNavList() {
  return <NavList pathname={usePathname()} />;
}

function Sidebar() {
  const router = useRouter();
  const session = useSession();

  async function signOut() {
    await authApi.logout().catch(() => undefined);
    router.replace("/login");
  }

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Bot className="size-4" aria-hidden />
        </div>
        <div className="min-w-0">
          {session ? (
            <p className="truncate text-sm font-semibold">{session.organization.name}</p>
          ) : (
            <Skeleton className="h-4 w-32" />
          )}
          <p className="text-xs text-muted-foreground">Support platform</p>
        </div>
      </div>
      <Separator />
      {/* The current path is URL data: read it inside Suspense (Next.js 16). */}
      <Suspense fallback={<NavList pathname={null} />}>
        <ActiveNavList />
      </Suspense>
      <div className="space-y-2 p-4">
        {session ? (
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{session.me.display_name}</p>
            <p className="truncate text-xs text-muted-foreground">{session.me.email}</p>
            <Badge variant="secondary" className="mt-1">
              {session.me.role.replace("_", " ")}
            </Badge>
          </div>
        ) : (
          <div className="space-y-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-40" />
          </div>
        )}
        <Button variant="outline" size="sm" className="w-full" onClick={signOut}>
          <LogOut aria-hidden /> Sign out
        </Button>
      </div>
    </aside>
  );
}

export function DashboardShell({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <div className="flex min-h-screen flex-1">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </SessionProvider>
  );
}
