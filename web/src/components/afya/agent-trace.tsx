"use client";

import { Brain, Gavel, PauseCircle, Wrench } from "lucide-react";

import type { TraceStep } from "@/api/contract";
import { ApiError } from "@/lib/api";
import { useTrace } from "@/lib/queries";
import { clock, useNow } from "@/lib/time";
import { cn } from "@/lib/utils";

/** Run id of the agent run that follows a reading: `<visit>:<bare observation id>` (docs/api.md Q8). */
export function runIdFor(visitId: string, obsId: string): string {
  return `${visitId}:${obsId.split("/").pop()}`;
}

const KIND = {
  tool: { icon: Wrench, label: "Tool call" },
  model: { icon: Brain, label: "Model call" },
  decision: { icon: Gavel, label: "Decision" },
  gate: { icon: PauseCircle, label: "Gate" },
} as const;

function ServerTag({ step }: { step: TraceStep }) {
  if (step.kind === "tool" && step.server === "ours")
    return <Tag className="border-agent/30 bg-agent-soft text-agent-foreground">ours · afya-mcp</Tag>;
  if (step.kind === "tool" && step.server === "borrowed")
    return <Tag className="border-sky-600/25 bg-sky-500/10 text-sky-800 dark:text-sky-300">borrowed · WSO2 FHIR</Tag>;
  if (step.kind === "model")
    return (
      <Tag className="border-border bg-muted text-foreground">
        language model · {step.cost_usd ? "remote (synthetic data only)" : "local"}
      </Tag>
    );
  if (step.kind === "decision") return <Tag className="border-foreground/20 bg-background">fixed code checks it</Tag>;
  return <Tag className="border-ok/30 bg-ok-soft text-ok">human in the loop</Tag>;
}

function Tag({ className, children }: { className?: string; children: React.ReactNode }) {
  return <span className={cn("inline-flex h-5 items-center rounded-full border px-2 text-[10.5px] font-semibold", className)}>{children}</span>;
}

function ms(v: number | null): string {
  if (v === null) return "";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
}

/** W5 "glass box" as a plain ordered list (E7-5). Polls while the run is still going. */
export function AgentTrace({ runId, live = true }: { runId: string; live?: boolean }) {
  const q = useTrace(runId, live);
  const now = useNow(1000);
  if (q.isPending) return <div className="h-32 animate-pulse rounded-xl bg-muted" />;
  if (q.error instanceof ApiError && q.error.status === 404)
    return <p className="text-sm text-muted-foreground">No agent run for this reading yet.</p>;
  if (q.isError) return <p className="text-sm text-muted-foreground">The trace is not available right now.</p>;

  const steps = q.data;
  // The contract has no run status: a run counts as working while its last step is recent and not the final gate.
  const last = steps[steps.length - 1];
  const working = !!last && last.kind !== "gate" && now - Date.parse(last.at) < 15_000;
  const tools = steps.filter((s) => s.kind === "tool");
  const ours = tools.filter((s) => s.server === "ours").length;
  const models = steps.filter((s) => s.kind === "model");
  const tokens = models.reduce((n, s) => n + (s.tokens_in ?? 0) + (s.tokens_out ?? 0), 0);
  const cost = steps.reduce((n, s) => n + (s.cost_usd ?? 0), 0);
  const modelMs = models.reduce((n, s) => n + (s.latency_ms ?? 0), 0);

  return (
    <div data-testid="trace">
      <ol className="space-y-2">
        {steps.map((s) => {
          const K = KIND[s.kind];
          return (
            <li
              key={s.step}
              data-kind={s.kind}
              data-server={s.server ?? undefined}
              className={cn(
                "animate-rise rounded-xl border bg-card p-3",
                s.kind === "decision" && "border-foreground/25 shadow-sm",
                s.kind === "gate" && "border-ok/35 bg-ok-soft/40",
              )}
            >
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span className="tnum grid size-6 place-items-center rounded-md bg-muted font-mono text-[11px] font-semibold text-muted-foreground">
                  {s.step}
                </span>
                <K.icon className="size-4 text-muted-foreground" aria-label={K.label} />
                <code className="font-mono text-sm font-semibold">{s.name}</code>
                <ServerTag step={s} />
                <span className="tnum ml-auto font-mono text-[11px] text-muted-foreground">
                  {[ms(s.latency_ms), s.tokens_in !== null ? `${s.tokens_in} → ${s.tokens_out} tokens` : "", s.cost_usd !== null ? `$${s.cost_usd.toFixed(2)}` : "", clock(s.at)]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              <p className="mt-1.5 pl-[34px] text-sm [overflow-wrap:anywhere]">
                <span className="text-muted-foreground">{s.args_summary}</span>
                <span className="mx-1.5 text-muted-foreground">→</span>
                <span className="font-medium">{s.result_summary}</span>
              </p>
              {s.cited_ids.length > 0 && (
                <p className="mt-1.5 flex flex-wrap gap-1 pl-[34px]">
                  {s.cited_ids.map((id) => (
                    <code key={id} className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                      {id}
                    </code>
                  ))}
                </p>
              )}
            </li>
          );
        })}
        {working && live && (
          <li className="flex items-center gap-2 rounded-xl border border-dashed p-3 text-sm text-agent-foreground">
            <span className="flex gap-1" aria-hidden>
              <span className="thinking-dot size-1.5 rounded-full bg-agent" />
              <span className="thinking-dot size-1.5 rounded-full bg-agent" />
              <span className="thinking-dot size-1.5 rounded-full bg-agent" />
            </span>
            The watch agent is working…
          </li>
        )}
      </ol>
      {steps.length > 0 && (
        <p className="tnum mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            {tools.length} tool calls ({ours} ours, {tools.length - ours} borrowed)
          </span>
          <span>
            {models.length} model call{models.length === 1 ? "" : "s"} · {tokens} tokens · {ms(modelMs) || "0 ms"}
          </span>
          <span>cost ${cost.toFixed(2)}</span>
          <span>read-only tools only; the model never writes</span>
        </p>
      )}
    </div>
  );
}
