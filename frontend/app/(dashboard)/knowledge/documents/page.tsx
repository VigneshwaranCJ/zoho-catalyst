"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { Loader2, Search } from "lucide-react";

import { KnowledgeTabs } from "@/components/knowledge/knowledge-tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { knowledgeDocsApi, type KnowledgeDocumentItem, type SearchHit } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function DocumentsPage() {
  const [docs, setDocs] = useState<KnowledgeDocumentItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let cancelled = false;
    knowledgeDocsApi.documents().then((d) => !cancelled && setDocs(d)).catch(() => !cancelled && setDocs([]));
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return setHits(null);
    setSearching(true);
    try {
      setHits((await knowledgeDocsApi.search(query.trim())).hits);
    } finally {
      setSearching(false);
    }
  }

  const live = docs?.filter((d) => d.status === "live") ?? [];
  return (
    <div className="space-y-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
        <p className="text-sm text-muted-foreground">
          Published knowledge in Open Knowledge Format, versioned in Git.
        </p>
      </div>
      <KnowledgeTabs current="documents" />

      <Card>
        <CardHeader>
          <CardTitle>Search the knowledge</CardTitle>
          <CardDescription>Try a customer question, e.g. &ldquo;Can I return it after 15 days?&rdquo;</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={onSearch} className="flex gap-2">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ask a question…" aria-label="Search query" />
            <Button type="submit" disabled={searching}>
              {searching ? <Loader2 className="animate-spin" aria-hidden /> : <Search aria-hidden />} Search
            </Button>
          </form>
          {hits && (
            <ol className="space-y-3" aria-label="Search results">
              {hits.length === 0 && <p className="text-sm text-muted-foreground">No matching sections.</p>}
              {hits.map((h) => (
                <li key={h.section_id} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={`/knowledge/documents/${h.document_id}`} className="font-medium hover:underline">
                      {h.heading_path.join(" › ")}
                    </Link>
                    {h.source_pages.map((p) => (
                      <Badge key={p} variant="outline">
                        p. {p}
                      </Badge>
                    ))}
                    <span className="ml-auto text-xs tabular-nums text-muted-foreground">score {h.score.toFixed(3)}</span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{h.snippet}</p>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documents</CardTitle>
          <CardDescription>{live.length} published</CardDescription>
        </CardHeader>
        <CardContent>
          {docs === null ? (
            <Skeleton className="h-24 w-full" />
          ) : docs.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No knowledge yet. Upload a document, then review and approve the AI drafts.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Version</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="max-w-96">
                      <Link href={`/knowledge/documents/${d.id}`} className="block truncate font-medium hover:underline">
                        {d.title}
                      </Link>
                      <span className="block truncate font-mono text-xs text-muted-foreground">{d.path}</span>
                    </TableCell>
                    <TableCell>
                      {d.doc_type}
                      {d.audience === "internal" && (
                        <Badge variant="outline" className="ml-1">
                          internal
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="space-x-1">
                      <Badge variant={d.status === "live" ? "default" : "secondary"}>{d.status}</Badge>
                      {d.pending_drafts > 0 && <Badge className="bg-amber-500 text-white">draft pending</Badge>}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{d.current_version_no ?? "-"}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(d.updated_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
