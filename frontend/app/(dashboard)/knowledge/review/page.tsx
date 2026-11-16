"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, ShieldAlert } from "lucide-react";

import { KnowledgeTabs } from "@/components/knowledge/knowledge-tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, knowledgeDocsApi, type DraftItem } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { useSession } from "../../session";

export default function ReviewPage() {
  const session = useSession();
  const canPublish = session?.me.permissions.includes("knowledge:publish") ?? false;
  const [drafts, setDrafts] = useState<DraftItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acknowledge, setAcknowledge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    knowledgeDocsApi
      .reviews()
      .then((items) => {
        if (cancelled) return;
        setDrafts(items);
        // Pre-select drafts without errors: the common case is "approve the batch".
        setSelected(new Set(items.filter((d) => d.error_count === 0).map((d) => d.version_id)));
      })
      .catch(() => !cancelled && setMessage({ ok: false, text: "Could not load drafts." }));
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const chosen = useMemo(() => drafts?.filter((d) => selected.has(d.version_id)) ?? [], [drafts, selected]);
  const needsAck = chosen.some((d) => d.has_injection_warnings);
  const hasErrors = chosen.some((d) => d.error_count > 0);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function approveSelected() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await knowledgeDocsApi.approve(
        chosen.map((d) => d.version_id),
        null,
        acknowledge,
      );
      setMessage({
        ok: true,
        text: `Published ${result.approved} document(s) in commit ${result.commit_sha.slice(0, 8)}.`,
      });
      setAcknowledge(false);
      setReloadKey((k) => k + 1);
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Approval failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
        <p className="text-sm text-muted-foreground">
          AI-drafted knowledge waits here until a person approves it. Only approved knowledge is
          used to answer customers.
        </p>
      </div>
      <KnowledgeTabs current="review" reviewCount={drafts?.length} />

      {message && (
        <Alert variant={message.ok ? "default" : "destructive"}>
          {message.ok ? <CheckCircle2 aria-hidden /> : <AlertTriangle aria-hidden />}
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Drafts waiting for review</CardTitle>
          <CardDescription>
            Open a draft to read it, see what changed, and check the warnings. Every statement is
            linked to the page it came from.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {drafts === null ? (
            <Skeleton className="h-24 w-full" />
          ) : drafts.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Nothing to review.</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    {canPublish && <TableHead className="w-8"><span className="sr-only">Select</span></TableHead>}
                    <TableHead>Document</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Checks</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drafts.map((d) => (
                    <TableRow key={d.version_id}>
                      {canPublish && (
                        <TableCell>
                          <input
                            type="checkbox"
                            aria-label={`Select ${d.title}`}
                            checked={selected.has(d.version_id)}
                            onChange={() => toggle(d.version_id)}
                            className="size-4"
                          />
                        </TableCell>
                      )}
                      <TableCell className="max-w-80">
                        <Link
                          href={`/knowledge/versions/${d.version_id}`}
                          className="block truncate font-medium hover:underline"
                        >
                          {d.title}
                        </Link>
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {d.path} · v{d.version_no} {d.is_update ? "(update)" : "(new)"}
                        </span>
                      </TableCell>
                      <TableCell>
                        {d.doc_type}
                        {d.audience === "internal" && (
                          <Badge variant="outline" className="ml-1">
                            internal
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="max-w-48 truncate text-muted-foreground">{d.source_name ?? "edit"}</TableCell>
                      <TableCell className="space-x-1 whitespace-nowrap">
                        {d.error_count > 0 && <Badge variant="destructive">{d.error_count} errors</Badge>}
                        {d.has_injection_warnings && (
                          <Badge className="bg-red-700 text-white hover:bg-red-700">
                            <ShieldAlert aria-hidden /> injection
                          </Badge>
                        )}
                        {d.warning_count > 0 && <Badge variant="secondary">{d.warning_count} warnings</Badge>}
                        {d.error_count === 0 && d.warning_count === 0 && <Badge variant="outline">clean</Badge>}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatDateTime(d.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {canPublish && (
                <div className="flex flex-wrap items-center gap-4 border-t pt-4">
                  {needsAck && (
                    <label className="flex items-center gap-2 text-sm text-red-700">
                      <input
                        type="checkbox"
                        checked={acknowledge}
                        onChange={(e) => setAcknowledge(e.target.checked)}
                        className="size-4"
                      />
                      I reviewed the prompt-injection warnings and the drafts are safe.
                    </label>
                  )}
                  <Button
                    onClick={() => void approveSelected()}
                    disabled={busy || chosen.length === 0 || hasErrors || (needsAck && !acknowledge)}
                  >
                    {busy && <Loader2 className="animate-spin" aria-hidden />}
                    Approve and publish {chosen.length} selected
                  </Button>
                  {hasErrors && (
                    <span className="text-sm text-destructive">Drafts with errors must be fixed first.</span>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
