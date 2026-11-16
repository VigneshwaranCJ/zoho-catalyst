"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, Pencil, ShieldCheck, Trash2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, knowledgeDocsApi, type KnowledgeDocumentDetail } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { useSession } from "../../../session";

const TIER_LABEL: Record<string, string> = {
  "human-reviewed": "Human-reviewed",
  "machine-confirmed": "Machine-checked only",
  unverified: "Unverified",
};

export function DocumentDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const session = useSession();
  const permissions = session?.me.permissions ?? [];
  const canEdit = permissions.includes("knowledge:edit");
  const canDelete = permissions.includes("knowledge:publish");
  const [doc, setDoc] = useState<KnowledgeDocumentDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    knowledgeDocsApi
      .document(id)
      .then((d) => !cancelled && setDoc(d))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function saveDraft() {
    setBusy(true);
    setError(null);
    try {
      const version = await knowledgeDocsApi.edit(id, draft);
      router.push(`/knowledge/versions/${version.version_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      setBusy(false);
    }
  }

  async function archive() {
    if (!doc || !window.confirm(`Remove "${doc.title}" from the published knowledge? Git keeps its history.`)) return;
    setBusy(true);
    try {
      await knowledgeDocsApi.archive(id);
      router.push("/knowledge/documents");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove.");
      setBusy(false);
    }
  }

  if (!doc) {
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

  return (
    <div className="space-y-6 p-8">
      <Link href="/knowledge/documents" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Back to documents
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{doc.title}</h1>
          <p className="font-mono text-xs text-muted-foreground">
            {doc.path} · {doc.doc_type} · audience: {doc.audience}
          </p>
          {doc.description && <p className="mt-1 text-sm text-muted-foreground">{doc.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          {doc.trust_tier && (
            <Badge variant={doc.trust_tier === "human-reviewed" ? "default" : "secondary"}>
              <ShieldCheck aria-hidden /> {TIER_LABEL[doc.trust_tier] ?? doc.trust_tier}
            </Badge>
          )}
          {canEdit && doc.content && !editing && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDraft(doc.content ?? "");
                setEditing(true);
              }}
            >
              <Pencil aria-hidden /> Edit
            </Button>
          )}
          {canDelete && (
            <Button variant="outline" size="sm" onClick={() => void archive()} disabled={busy}>
              <Trash2 aria-hidden /> Remove
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{editing ? "Edit (saved as a draft for review)" : "Published content"}</CardTitle>
          {editing && (
            <CardDescription>
              Keep the footnotes ([^...]) on every fact. Your edit is validated and must be approved before
              customers see it.
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {editing ? (
            <>
              <textarea
                aria-label="Document content"
                className="min-h-[28rem] w-full rounded-md border bg-transparent p-3 font-mono text-xs leading-relaxed"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                spellCheck={false}
              />
              <div className="flex gap-2">
                <Button onClick={() => void saveDraft()} disabled={busy || draft === doc.content}>
                  {busy && <Loader2 className="animate-spin" aria-hidden />} Save as draft
                </Button>
                <Button variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </>
          ) : doc.content ? (
            <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed">
              {doc.content}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">Not published yet: see the review queue.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Version history</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm">
            {doc.versions.map((v) => (
              <li key={v.version_id} className="flex flex-wrap items-center gap-2">
                <Link href={`/knowledge/versions/${v.version_id}`} className="font-medium hover:underline">
                  v{v.version_no}
                </Link>
                <Badge variant={v.review_status === "approved" ? "default" : "secondary"}>{v.review_status}</Badge>
                <span className="text-muted-foreground">by {v.generated_by}</span>
                <span className="text-muted-foreground">{formatDateTime(v.reviewed_at ?? v.created_at)}</span>
                {v.git_commit_sha && (
                  <span className="font-mono text-xs text-muted-foreground">commit {v.git_commit_sha.slice(0, 8)}</span>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
