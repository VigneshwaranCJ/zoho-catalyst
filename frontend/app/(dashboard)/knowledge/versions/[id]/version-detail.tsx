"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, Check, Loader2, ShieldAlert, X } from "lucide-react";

import { DiffView } from "@/components/knowledge/diff-view";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, knowledgeDocsApi, type VersionDetail as Version } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { useSession } from "../../../session";

export function VersionDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const session = useSession();
  const canPublish = session?.me.permissions.includes("knowledge:publish") ?? false;
  const [version, setVersion] = useState<Version | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [acknowledge, setAcknowledge] = useState(false);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [view, setView] = useState<"content" | "diff">("content");

  useEffect(() => {
    let cancelled = false;
    knowledgeDocsApi
      .version(id)
      .then((v) => !cancelled && setVersion(v))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function decide(action: "approve" | "reject") {
    if (!version) return;
    setBusy(action);
    setError(null);
    try {
      if (action === "approve") {
        await knowledgeDocsApi.approve([version.version_id], note || null, acknowledge);
      } else {
        await knowledgeDocsApi.reject(version.version_id, note || null);
      }
      router.push("/knowledge/review");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
      setBusy(null);
    }
  }

  if (!version) {
    return (
      <div className="p-8">
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <Skeleton className="h-64 w-full" />
        )}
      </div>
    );
  }

  const pending = version.review_status === "pending";
  const { errors, warnings } = version.validation;
  return (
    <div className="space-y-6 p-8">
      <Link href="/knowledge/review" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Back to review
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{version.title}</h1>
          <p className="font-mono text-xs text-muted-foreground">
            {version.path} · version {version.version_no} · {version.doc_type} · by {version.generated_by} ·{" "}
            {formatDateTime(version.created_at)}
          </p>
        </div>
        <Badge variant={pending ? "secondary" : "outline"}>{version.review_status}</Badge>
      </div>

      {version.has_injection_warnings && (
        <Alert variant="destructive">
          <ShieldAlert aria-hidden />
          <AlertTitle>Possible prompt injection in the source document</AlertTitle>
          <AlertDescription>
            The original document contains text that tries to give instructions to an AI (often hidden
            from human readers). The AI was told to ignore it and suspicious statements were removed,
            but please read this draft carefully before publishing.
          </AlertDescription>
        </Alert>
      )}
      {errors.length > 0 && (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden />
          <AlertTitle>{errors.length} validation error(s): must be fixed before publishing</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {errors.map((e, i) => (
                <li key={i}>{e.message}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {warnings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{warnings.length} warning(s)</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="max-h-48 list-disc space-y-1 overflow-y-auto pl-4 text-sm text-muted-foreground">
              {warnings.map((w, i) => (
                <li key={i}>{w.message}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">Document</CardTitle>
          <div className="flex gap-1">
            <Button size="sm" variant={view === "content" ? "secondary" : "ghost"} onClick={() => setView("content")}>
              Full text
            </Button>
            <Button size="sm" variant={view === "diff" ? "secondary" : "ghost"} onClick={() => setView("diff")}>
              Changes
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {view === "content" ? (
            <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed">
              {version.content}
            </pre>
          ) : (
            <DiffView diff={version.diff} />
          )}
        </CardContent>
      </Card>

      {pending && canPublish && (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <div className="grid gap-2">
              <Label htmlFor="review-note">Note (optional, saved in the history)</Label>
              <textarea
                id="review-note"
                className="min-h-16 rounded-md border bg-transparent px-3 py-2 text-sm"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={2000}
              />
            </div>
            {version.has_injection_warnings && (
              <label className="flex items-center gap-2 text-sm text-red-700">
                <input type="checkbox" className="size-4" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />
                I read the warnings and this draft is safe to publish.
              </label>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex gap-2">
              <Button
                onClick={() => void decide("approve")}
                disabled={busy !== null || errors.length > 0 || (version.has_injection_warnings && !acknowledge)}
              >
                {busy === "approve" ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
                Approve and publish
              </Button>
              <Button variant="outline" onClick={() => void decide("reject")} disabled={busy !== null}>
                {busy === "reject" ? <Loader2 className="animate-spin" aria-hidden /> : <X aria-hidden />}
                Reject
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
