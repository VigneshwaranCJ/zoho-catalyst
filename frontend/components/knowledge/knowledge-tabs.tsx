"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

const TABS = [
  { key: "sources", href: "/knowledge", label: "Sources" },
  { key: "review", href: "/knowledge/review", label: "Review" },
  { key: "documents", href: "/knowledge/documents", label: "Documents" },
] as const;

export type KnowledgeTab = (typeof TABS)[number]["key"];

/** Sub-navigation shared by the knowledge pages (current tab passed in, no URL reading). */
export function KnowledgeTabs({ current, reviewCount }: { current: KnowledgeTab; reviewCount?: number }) {
  return (
    <nav aria-label="Knowledge sections" className="flex gap-1 border-b">
      {TABS.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          aria-current={current === tab.key ? "page" : undefined}
          className={cn(
            "-mb-px border-b-2 px-3 py-2 text-sm",
            current === tab.key
              ? "border-primary font-medium text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
          {tab.key === "review" && reviewCount ? (
            <span className="ml-1.5 rounded-full bg-amber-500 px-1.5 text-xs text-white">{reviewCount}</span>
          ) : null}
        </Link>
      ))}
    </nav>
  );
}
