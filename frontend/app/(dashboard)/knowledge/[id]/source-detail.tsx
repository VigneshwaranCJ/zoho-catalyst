"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { JobStatusBadge } from "@/components/knowledge/job-status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ACTIVE_JOB_STATUSES, ApiError, knowledgeApi, type KnowledgeSourceDetail } from "@/lib/api";
import { formatBytes, formatDateTime, SOURCE_TYPE_LABELS } from "@/lib/format";

const PAGE_MARKER = /<!-- page: (\d+) -->/;

/** Split extracted Markdown into [{page, text}] using the `<!-- page: N -->` markers. */
function splitPages(markdown: string): { page: number | null; text: string }[] {
  const body = markdown.replace(/^<!-- source:[^\n]*-->\n*/, ""); // provenance header
  const parts = body.split(PAGE_MARKER);
  if (parts.length === 1) return [{ page: null, text: body.trim() }];
  const pages: { page: number | null; text: string }[] = [];
  for (let i = 1; i < parts.length; i += 2) {
    pages.push({ page: Number(parts[i]), text: (parts[i + 1] ?? "").trim() });
  }
  return pages;
}

export function SourceDetail() {
  const { id } = useParams<{ id: string }>();
  const [source, setSource] = useState<KnowledgeSourceDetail | null>(null);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const detail = await knowledgeApi.get(id);
        const text = detail.job?.status === "extracted" ? await knowledgeApi.extracted(id) : null;
        if (cancelled) return;
        setSource(detail);
        setMarkdown(text);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError && err.status === 404 ? "Source not found." : "Could not load this source.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, reloadKey]);

  const active = source?.job ? ACTIVE_JOB_STATUSES.includes(source.job.status) : false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setReloadKey((k) => k + 1), 3000);
    return () => clearInterval(timer);
  }, [active]);

  const pages = useMemo(() => (markdown ? splitPages(markdown) : []), [markdown]);

  return (
    <div className="space-y-6 p-8">
      <Link href="/knowledge" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Back to knowledge
      </Link>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!source && !error && <Skeleton className="h-32 w-full" />}

      {source && (
        <>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold tracking-tight">{source.name}</h1>
              {source.uri && (
                <a
                  href={source.uri}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline"
                >
                  {source.uri} <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </div>
            <JobStatusBadge job={source.job} />
          </div>

          {source.job?.error && (
            <Alert variant={source.job.status === "failed" ? "destructive" : "default"}>
              <AlertDescription>{source.job.error}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Details</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">Type</dt>
                  <dd>{SOURCE_TYPE_LABELS[source.source_type] ?? source.source_type}</dd>
                  <dt className="text-muted-foreground">Size</dt>
                  <dd>{formatBytes(source.size_bytes)}</dd>
                  <dt className="text-muted-foreground">Pages</dt>
                  <dd>{source.page_count ?? "no fixed pages"}</dd>
                  <dt className="text-muted-foreground">Tables found</dt>
                  <dd>{String(source.stats.tables ?? "-")}</dd>
                  <dt className="text-muted-foreground">Extraction time</dt>
                  <dd>
                    {typeof source.stats.duration_ms === "number"
                      ? `${(source.stats.duration_ms / 1000).toFixed(1)} s`
                      : "-"}
                  </dd>
                  <dt className="text-muted-foreground">Extractor</dt>
                  <dd>{String(source.stats.extractor ?? "-")}</dd>
                  <dt className="text-muted-foreground">Added</dt>
                  <dd>{formatDateTime(source.created_at)}</dd>
                  <dt className="text-muted-foreground">Fingerprint</dt>
                  <dd className="truncate font-mono text-xs" title={source.sha256 ?? undefined}>
                    {source.sha256 ? `${source.sha256.slice(0, 16)}…` : "-"}
                  </dd>
                </dl>
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Outline</CardTitle>
                <CardDescription>Headings found in the document, with the page they are on.</CardDescription>
              </CardHeader>
              <CardContent>
                {source.outline.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {active ? "Available once extraction finishes." : "No headings found."}
                  </p>
                ) : (
                  <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">
                    {source.outline.map((h, i) => (
                      <li key={i} className="flex items-center justify-between gap-2">
                        <span className="truncate">{h.text}</span>
                        {h.page != null && (
                          <Badge variant="outline" className="shrink-0">
                            p. {h.page}
                          </Badge>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          {pages.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Extracted text</CardTitle>
                <CardDescription>
                  Exactly what the AI assistant will be able to read and cite. Shown as plain text.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {pages.map((p, i) => (
                  <section key={i} aria-label={p.page ? `Page ${p.page}` : "Document text"}>
                    {p.page != null && (
                      <div className="mb-1 flex items-center gap-2">
                        <Badge>Page {p.page}</Badge>
                        <div className="h-px flex-1 bg-border" />
                      </div>
                    )}
                    {/* Plain text on purpose: content comes from untrusted documents. */}
                    <pre className="whitespace-pre-wrap rounded-md bg-muted/50 p-3 font-mono text-xs leading-relaxed">
                      {p.text || "(empty page)"}
                    </pre>
                  </section>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
