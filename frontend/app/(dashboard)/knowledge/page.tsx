"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { FileUp, Globe, Loader2, RotateCcw, Trash2, Upload } from "lucide-react";

import { JobStatusBadge } from "@/components/knowledge/job-status-badge";
import { KnowledgeTabs } from "@/components/knowledge/knowledge-tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ACTIVE_JOB_STATUSES,
  ApiError,
  knowledgeApi,
  type KnowledgeSource,
  type UploadItem,
} from "@/lib/api";
import { formatBytes, formatDateTime, SOURCE_TYPE_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSession } from "../session";

const ACCEPT = ".pdf,.docx,.html,.htm,.md,.markdown,.txt";
const POLL_MS = 3000;

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : "Could not reach the server.";
}

export default function KnowledgePage() {
  const session = useSession();
  const permissions = session?.me.permissions ?? [];
  const canEdit = permissions.includes("knowledge:edit");
  const canDelete = permissions.includes("knowledge:publish");

  const [sources, setSources] = useState<KnowledgeSource[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumping this number re-runs the loading effect below ("refresh").
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = useCallback(async () => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    knowledgeApi
      .list()
      .then((data) => {
        if (cancelled) return;
        setSources(data);
        setLoadError(null);
      })
      .catch((err) => !cancelled && setLoadError(errorText(err)));
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  // Poll while any job is still running, so status badges update by themselves.
  const busy = sources?.some((s) => s.job && ACTIVE_JOB_STATUSES.includes(s.job.status)) ?? false;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setReloadKey((k) => k + 1), POLL_MS);
    return () => clearInterval(timer);
  }, [busy]);

  return (
    <div className="space-y-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
        <p className="text-sm text-muted-foreground">
          Upload manuals, policies and FAQs. Each document is read, its text extracted with page
          numbers, and prepared for the AI assistant.
        </p>
      </div>
      <KnowledgeTabs current="sources" />

      {canEdit && (
        <div className="grid gap-4 lg:grid-cols-2">
          <UploadCard onDone={refresh} />
          <UrlCard onDone={refresh} />
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Sources</CardTitle>
          <CardDescription>
            {busy ? "Processing… this list updates automatically." : "All uploaded documents and web pages."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loadError && (
            <Alert variant="destructive" className="mb-4">
              <AlertDescription>{loadError}</AlertDescription>
            </Alert>
          )}
          {sources === null ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : sources.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No sources yet. {canEdit ? "Upload a document to get started." : ""}
            </p>
          ) : (
            <SourcesTable sources={sources} canEdit={canEdit} canDelete={canDelete} onChange={refresh} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function UploadCard({ onDone }: { onDone: () => Promise<void> }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(files: File[]) {
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    setResults(null);
    try {
      const response = await knowledgeApi.upload(files);
      setResults(response.items);
      await onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void upload(Array.from(event.dataTransfer.files));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileUp className="size-4" aria-hidden /> Upload documents
        </CardTitle>
        <CardDescription>PDF, Word (.docx), HTML, Markdown or text. Up to 20 files, 50 MB each.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          role="button"
          tabIndex={0}
          aria-label="Choose files to upload, or drop them here"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-sm text-muted-foreground transition-colors",
            dragging && "border-primary bg-primary/5",
          )}
        >
          {uploading ? (
            <Loader2 className="size-6 animate-spin" aria-hidden />
          ) : (
            <Upload className="size-6" aria-hidden />
          )}
          <span>{uploading ? "Uploading…" : "Drop files here or click to choose"}</span>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          data-testid="file-input"
          onChange={(e) => void upload(Array.from(e.target.files ?? []))}
        />
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {results && (
          <ul className="space-y-1 text-sm" aria-live="polite">
            {results.map((r, i) => (
              <li key={`${r.filename}-${i}`} className="flex gap-2">
                <span className="font-medium">{r.filename}:</span>
                <span
                  className={cn(
                    r.status === "rejected" && "text-destructive",
                    r.status === "duplicate" && "text-amber-600",
                  )}
                >
                  {r.status === "created" && "uploaded, processing started"}
                  {r.status === "duplicate" && "already uploaded (skipped)"}
                  {r.status === "rejected" && r.error}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function UrlCard({ onDone }: { onDone: () => Promise<void> }) {
  const [url, setUrl] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    try {
      await knowledgeApi.addUrl(url.trim());
      setMessage({ ok: true, text: "Added. The page will be fetched in the background." });
      setUrl("");
      await onDone();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="size-4" aria-hidden /> Add a web page
        </CardTitle>
        <CardDescription>
          A public page such as an online FAQ. Internal or private network addresses are refused.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-3">
          <div className="grid gap-2">
            <Label htmlFor="source-url">Page URL</Label>
            <Input
              id="source-url"
              type="url"
              inputMode="url"
              placeholder="https://www.example.com/support/faq"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={pending || url.trim().length < 8}>
            {pending && <Loader2 className="animate-spin" aria-hidden />}
            Add page
          </Button>
          {message && (
            <p className={cn("text-sm", message.ok ? "text-emerald-700" : "text-destructive")} role="status">
              {message.text}
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

function SourcesTable({
  sources,
  canEdit,
  canDelete,
  onChange,
}: {
  sources: KnowledgeSource[];
  canEdit: boolean;
  canDelete: boolean;
  onChange: () => Promise<void>;
}) {
  const [actionError, setActionError] = useState<string | null>(null);

  async function retry(id: string) {
    try {
      await knowledgeApi.retry(id);
      await onChange();
    } catch (err) {
      setActionError(errorText(err));
    }
  }

  async function remove(source: KnowledgeSource) {
    if (!window.confirm(`Delete "${source.name}"? It will no longer be used for answers.`)) return;
    try {
      await knowledgeApi.remove(source.id);
      await onChange();
    } catch (err) {
      setActionError(errorText(err));
    }
  }

  return (
    <>
      {actionError && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="text-right">Size</TableHead>
            <TableHead className="text-right">Pages</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Added</TableHead>
            <TableHead className="sr-only">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="max-w-72">
                <Link href={`/knowledge/${s.id}`} className="block truncate font-medium hover:underline">
                  {s.name}
                </Link>
                {s.job?.status === "failed" && s.job.error && (
                  <p className="truncate text-xs text-destructive" title={s.job.error}>
                    {s.job.error}
                  </p>
                )}
              </TableCell>
              <TableCell>{SOURCE_TYPE_LABELS[s.source_type] ?? s.source_type}</TableCell>
              <TableCell className="text-right tabular-nums">{formatBytes(s.size_bytes)}</TableCell>
              <TableCell className="text-right tabular-nums">{s.page_count ?? "-"}</TableCell>
              <TableCell>
                <JobStatusBadge job={s.job} />
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatDateTime(s.created_at)}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap">
                {canEdit && s.job?.status === "failed" && (
                  <Button variant="ghost" size="icon" onClick={() => void retry(s.id)} aria-label={`Retry ${s.name}`}>
                    <RotateCcw aria-hidden />
                  </Button>
                )}
                {canDelete && (
                  <Button variant="ghost" size="icon" onClick={() => void remove(s)} aria-label={`Delete ${s.name}`}>
                    <Trash2 aria-hidden />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
