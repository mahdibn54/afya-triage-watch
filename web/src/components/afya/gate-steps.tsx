"use client";

import { Check, Loader2, X } from "lucide-react";

import type { Gate, GateName } from "@/api/contract";
import { useGates, useUserName } from "@/lib/queries";
import { clock } from "@/lib/time";
import { cn } from "@/lib/utils";

const LABEL: Record<GateName, (by: string) => string> = {
  proposed: () => "Proposed by the watch agent",
  paused: () => "Paused for a nurse",
  confirmed: (by) => (by ? `Confirmed by ${by}` : "Confirmed by a nurse or clinician"),
  claimed: () => "Command claimed",
  written: () => "Written to the record",
  audited: () => "Audited",
};

const ROLE_WORD: Record<string, string> = { manager: "manager", nurse: "nurse", clinician: "clinician" };

/** W4 as a list of ticks (E7-7): the human-in-the-loop path of one proposal, each step with its time. */
export function GateSteps({ proposalId, outcome }: { proposalId: string; outcome?: "rejected" }) {
  const q = useGates(proposalId, outcome !== "rejected");
  const name = useUserName();
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  if (q.isError || !q.data) return <p className="text-sm text-muted-foreground">Gate steps are not available right now.</p>;

  const gates = q.data;
  const firstOpen = gates.findIndex((g) => !g.at);

  return (
    <ol data-testid="gates" className="relative space-y-0">
      {gates.map((g: Gate, i) => {
        const done = !!g.at;
        const isNext = i === firstOpen && !outcome;
        const stopped = outcome === "rejected" && !done && i === firstOpen;
        return (
          <li key={g.gate} data-gate={g.gate} data-done={done || undefined} className="relative flex gap-3 pb-3 last:pb-0">
            {i < gates.length - 1 && (
              <span aria-hidden className={cn("absolute top-7 bottom-0 left-[13px] w-0.5", done && gates[i + 1].at ? "bg-ok" : "bg-border")} />
            )}
            <span
              className={cn(
                "relative z-10 grid size-7 shrink-0 place-items-center rounded-full border-2",
                done && "animate-tick border-ok bg-ok text-white",
                isNext && "border-agent bg-agent-soft text-agent",
                stopped && "border-muted-foreground/40 bg-muted text-muted-foreground",
                !done && !isNext && !stopped && "border-border bg-background text-muted-foreground",
              )}
            >
              {done ? <Check className="size-4" strokeWidth={3} /> : stopped ? <X className="size-3.5" /> : isNext ? <Loader2 className="size-3.5 animate-spin" /> : null}
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <p className={cn("text-sm font-medium", !done && "text-muted-foreground")}>
                  {LABEL[g.gate](g.gate === "confirmed" ? name(g.by) : "")}
                  {stopped && " · not reached: rejected"}
                  {isNext && g.gate === "confirmed" && " · waiting"}
                </p>
                <time className="tnum font-mono text-xs text-muted-foreground" dateTime={g.at ?? undefined}>
                  {g.at ? clock(g.at) : "–"}
                </time>
              </div>
              {g.refused.map((r, j) => (
                <p
                  key={j}
                  data-testid="refused"
                  className="mt-1 flex items-center gap-1.5 rounded-lg bg-destructive/8 px-2 py-1 text-xs text-destructive"
                >
                  <X className="size-3.5 shrink-0" strokeWidth={3} />
                  Refused: {name(r.by)} ({ROLE_WORD[r.role] ?? r.role}) tried to confirm
                  <time className="tnum ml-auto font-mono" dateTime={r.at}>
                    {clock(r.at)}
                  </time>
                </p>
              ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
