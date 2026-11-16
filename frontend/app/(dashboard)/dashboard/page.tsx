"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { useSession } from "../session";

// KPI tiles from the spec. Values arrive once conversations exist (Phase 7/8);
// until then each tile says honestly that there is no data yet.
const KPIS = [
  { title: "Total conversations", hint: "All widget conversations" },
  { title: "Resolved conversations", hint: "Answered without escalation" },
  { title: "Escalated tickets", hint: "Handed to a human in Zoho Desk" },
  { title: "Unanswered questions", hint: "No reliable answer in the knowledge" },
  { title: "Customer satisfaction", hint: "Thumbs up / down feedback" },
  { title: "AI response accuracy", hint: "From the evaluation set" },
  { title: "Average response time", hint: "Time to first token" },
];

export default function DashboardPage() {
  const session = useSession();
  return (
    <div className="space-y-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {session ? `Welcome, ${session.me.display_name}` : "Welcome"}
        </h1>
        <p className="text-sm text-muted-foreground">
          Overview of your AI support. Metrics appear once customers start chatting.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {KPIS.map((kpi) => (
          <Card key={kpi.title}>
            <CardHeader>
              <CardDescription>{kpi.title}</CardDescription>
              <CardTitle className="text-3xl tabular-nums text-muted-foreground">-</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">{kpi.hint} · no data yet</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
