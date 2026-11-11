import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { SourceDetail } from "./source-detail";

// Server component shell. The client view reads the URL (`useParams`), which in
// Next.js 16 must happen inside a <Suspense> boundary so the rest of the page
// can be prerendered without knowing the id.
export default function SourceDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-4 p-8">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-32 w-full" />
        </div>
      }
    >
      <SourceDetail />
    </Suspense>
  );
}
