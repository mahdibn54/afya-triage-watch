"use client";

import { CheckCircle2, ChevronDown, Flag, PenLine, ScanEye, Sparkles, XCircle } from "lucide-react";

import type { Me, Proposal, QueuePatient } from "@/api/contract";
import { AgentTrace, runIdFor } from "@/components/afya/agent-trace";
import { ApprovalCard } from "@/components/afya/approval-card";
import { TargetBar } from "@/components/afya/board";
import { ColourChip } from "@/components/afya/colour-chip";
import { GateSteps } from "@/components/afya/gate-steps";
import { NoticeCallout } from "@/components/afya/notice-chip";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useAcknowledgeNotice, useAcknowledgeProposal, useProposals, useQueue, useTimeline, useUserName } from "@/lib/queries";
import { SATS } from "@/lib/sats";
import { clockShort, useNow } from "@/lib/time";
import { cn } from "@/lib/utils";

export function VisitPanel({
  me,
  visitId,
  onClose,
  onRecord,
}: {
  me: Me;
  visitId: string | null;
  onClose: () => void;
  onRecord: (p: QueuePatient) => void;
}) {
  return (
    <Sheet open={!!visitId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="w-full gap-0 overflow-y-auto bg-background p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-[820px]"
      >
        {visitId && <VisitBody me={me} visitId={visitId} onRecord={onRecord} />}
      </SheetContent>
    </Sheet>
  );
}

function VisitBody({ me, visitId, onRecord }: { me: Me; visitId: string; onRecord: (p: QueuePatient) => void }) {
  const queue = useQueue();
  const all = useProposals("all");
  const timeline = useTimeline(visitId);
  const now = useNow(1000);
  const name = useUserName();
  const ackProposal = useAcknowledgeProposal();
  const ackNotice = useAcknowledgeNotice();
  const canWrite = me.role !== "manager";

  const p = queue.data?.patients.find((x) => x.visit_id === visitId);
  const proposals = (all.data ?? []).filter((x) => x.visit_id === visitId);
  const pending = proposals.filter((x) => x.status === "pending");
  const decided = proposals.filter((x) => x.status === "approved" || x.status === "rejected");
  const unreviewed = proposals.filter((x) => x.status === "superseded" && !x.reviewed);

  if (!p) {
    return (
      <div className="p-8">
        <SheetTitle>Patient</SheetTitle>
        <p className="mt-2 text-sm text-muted-foreground">{queue.isPending ? "Loading…" : "This visit is no longer in the waiting room."}</p>
      </div>
    );
  }

  // Runs: the one that followed the latest reading first, then any older run that made a proposal.
  const readings = timeline.data?.readings ?? [];
  const latestRun = readings.length ? runIdFor(visitId, readings[readings.length - 1].obs_id) : null;
  const olderRuns = [
    ...new Set([...readings.map((r) => runIdFor(visitId, r.obs_id)).reverse(), ...proposals.map((x) => runIdFor(visitId, x.obs_id))]),
  ].filter((r) => r !== latestRun);

  // not_reviewed is shown below with its own "mark as seen" action.
  const visitNotices = p.notices.filter((n) => n.code !== "not_reviewed");

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-10 border-b bg-background/90 px-5 py-4 pr-14 backdrop-blur-md sm:px-7">
        <div className="flex flex-wrap items-center gap-3">
          <SheetTitle className="font-mono text-2xl font-semibold tracking-tight">{p.patient_label}</SheetTitle>
          <ColourChip colour={p.confirmed_colour} />
          {p.flags.includes("second_look") && (
            <span className="inline-flex h-7 items-center gap-1 rounded-lg border px-2 text-xs font-semibold">
              <Flag className="size-3.5" /> Second look confirmed
            </span>
          )}
          {canWrite && (
            <button
              type="button"
              onClick={() => onRecord(p)}
              className="ml-auto inline-flex h-11 items-center gap-1.5 rounded-xl border bg-card px-3.5 text-sm font-medium hover:shadow-sm"
            >
              <PenLine className="size-4" /> Record vitals
            </button>
          )}
        </div>
        <SheetDescription className="tnum mt-1">
          Arrived {clockShort(p.arrived_at)} · waited {Math.floor((now - Date.parse(p.arrived_at)) / 60000)} min · last reading{" "}
          {p.last_reading ? `TEWS ${p.last_reading.tews} at ${clockShort(p.last_reading.effective)}` : "none yet"}
        </SheetDescription>
        <div className="mt-3 max-w-md">
          <TargetBar p={p} now={now} />
        </div>
      </header>

      <div className="flex-1 space-y-5 px-5 py-6 sm:px-7">
        {visitNotices.map((n, i) => (
          <NoticeCallout
            key={`${n.code}-${i}`}
            code={n.code}
            action={
              n.notification_id && canWrite ? (
                <button
                  type="button"
                  onClick={() => ackNotice.mutate(n.notification_id!)}
                  className="h-9 shrink-0 rounded-lg border bg-background px-3 text-xs font-semibold hover:bg-muted"
                >
                  Dismiss
                </button>
              ) : undefined
            }
          />
        ))}

        {pending.map((x) => (
          <ApprovalCard key={x.id} me={me} proposal={x} />
        ))}

        {pending.length === 0 && decided.length === 0 && (
          <div className="rounded-2xl border border-dashed p-8 text-center">
            <Sparkles className="mx-auto size-6 text-muted-foreground" />
            <p className="mt-2 font-medium">No second look suggested</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The watch agent re-scores every new reading and checks the room every few minutes.
            </p>
          </div>
        )}

        {decided.map((x) => (
          <DecidedCard key={x.id} proposal={x} by={name(x.decided_by)} />
        ))}

        <section aria-labelledby="trace-title" className="rounded-2xl border bg-card/60 p-4 sm:p-5">
          <h2 id="trace-title" className="flex items-center gap-2 font-semibold">
            <ScanEye className="size-5 text-agent" /> What the watch agent did
          </h2>
          <p className="mt-0.5 mb-4 text-sm text-muted-foreground">
            Every step of the latest run, in order: our tools, the borrowed WSO2 FHIR tools, the model and the decision.
          </p>
          {latestRun ? (
            <AgentTrace key={latestRun} runId={latestRun} />
          ) : (
            <p className="text-sm text-muted-foreground">No reading yet, so no run.</p>
          )}
          {olderRuns.map((r) => (
            <details key={r} className="group mt-3 rounded-xl border bg-background">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium">
                <ChevronDown className="size-4 transition group-open:rotate-180" />
                Earlier run <code className="font-mono text-xs text-muted-foreground">{r}</code>
              </summary>
              <div className="px-3 pb-3">
                <AgentTrace runId={r} live={false} />
              </div>
            </details>
          ))}
        </section>

        {unreviewed.map((x) => (
          <NoticeCallout
            key={x.id}
            code="not_reviewed"
            action={
              canWrite ? (
                <button
                  type="button"
                  data-testid={`ack-${x.id}`}
                  disabled={ackProposal.isPending}
                  onClick={() => ackProposal.mutate(x.id)}
                  className="h-9 shrink-0 rounded-lg border bg-background px-3 text-xs font-semibold hover:bg-muted"
                >
                  Mark as seen
                </button>
              ) : undefined
            }
          >
            <p className="tnum mt-2 text-xs">
              Suggested {x.current_colour && SATS[x.current_colour].label} → {SATS[x.proposed_colour].label} at {clockShort(x.created_at)} (TEWS{" "}
              {x.tews_before ?? "–"} → {x.tews_after}).
            </p>
          </NoticeCallout>
        ))}
      </div>
    </div>
  );
}

function DecidedCard({ proposal: x, by }: { proposal: Proposal; by: string }) {
  const ok = x.status === "approved";
  return (
    <article
      data-testid={`decided-${x.status}`}
      className={cn("animate-rise rounded-2xl border p-5", ok ? "border-ok/30 bg-ok-soft/50" : "bg-muted/40")}
    >
      <div className="flex flex-wrap items-center gap-3">
        {ok ? <CheckCircle2 className="size-6 text-ok" /> : <XCircle className="size-6 text-muted-foreground" />}
        <p className="font-semibold">
          {ok ? "Second look confirmed" : "Suggestion rejected"} by {by}
        </p>
        <span className="tnum text-sm text-muted-foreground">at {clockShort(x.decided_at)}</span>
        <span className="ml-auto flex items-center gap-2 text-sm">
          <ColourChip colour={x.current_colour} size="sm" muted />→<ColourChip colour={x.proposed_colour} size="sm" />
          <span className="text-xs text-muted-foreground">suggested</span>
        </span>
      </div>
      <div className="mt-4 rounded-xl border bg-card p-4">
        <GateSteps proposalId={x.id} outcome={ok ? undefined : "rejected"} />
      </div>
    </article>
  );
}
