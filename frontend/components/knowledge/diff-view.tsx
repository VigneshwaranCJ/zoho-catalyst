import { cn } from "@/lib/utils";

/** Unified diff as plain text with +/- lines coloured (never rendered as HTML). */
export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <p className="text-sm text-muted-foreground">No changes.</p>;
  return (
    <pre className="max-h-[32rem] overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed">
      {diff.split("\n").map((line, i) => (
        <div
          key={i}
          className={cn(
            line.startsWith("+") && !line.startsWith("+++") && "bg-emerald-500/15 text-emerald-900 dark:text-emerald-200",
            line.startsWith("-") && !line.startsWith("---") && "bg-red-500/15 text-red-900 dark:text-red-200",
            line.startsWith("@@") && "text-sky-700",
          )}
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}
