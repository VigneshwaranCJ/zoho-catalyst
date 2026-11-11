import { AlertCircle, CheckCircle2, Clock, Eye, FileText, Loader2, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { IngestionJob } from "@/lib/api";

const LABELS: Record<IngestionJob["status"], string> = {
  queued: "Queued",
  fetching: "Fetching page",
  extracting: "Extracting text",
  extracted: "Text extracted",
  generating: "AI drafting",
  needs_review: "Needs review",
  reviewed: "Reviewed",
  failed: "Failed",
};

export function JobStatusBadge({ job }: { job: IngestionJob | null }) {
  if (!job) return <Badge variant="outline">No job</Badge>;
  const label = LABELS[job.status];
  switch (job.status) {
    case "reviewed":
      return (
        <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">
          <CheckCircle2 aria-hidden /> {label}
        </Badge>
      );
    case "needs_review":
      return (
        <Badge className="bg-amber-500 text-white hover:bg-amber-500">
          <Eye aria-hidden /> {label}
        </Badge>
      );
    case "extracted":
      return (
        <Badge variant="outline" title="Add an Anthropic API key to generate knowledge">
          <FileText aria-hidden /> {label}
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive" title={job.error ?? undefined}>
          <AlertCircle aria-hidden /> {label}
        </Badge>
      );
    case "queued":
      return (
        <Badge variant="secondary" title={job.error ?? undefined}>
          <Clock aria-hidden /> {job.attempts > 0 ? "Retrying" : label}
        </Badge>
      );
    case "generating":
      return (
        <Badge variant="secondary">
          <Sparkles className="animate-pulse" aria-hidden /> {label}
        </Badge>
      );
    default:
      return (
        <Badge variant="secondary">
          <Loader2 className="animate-spin" aria-hidden /> {label}
        </Badge>
      );
  }
}
