import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { VersionDetail } from "./version-detail";

// The client view reads the URL (useParams), so it renders inside <Suspense> (Next.js 16).
export default function VersionPage() {
  return (
    <Suspense fallback={<Skeleton className="m-8 h-64" />}>
      <VersionDetail />
    </Suspense>
  );
}
