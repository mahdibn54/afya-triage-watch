"use client";

import { Activity, ChevronRight, Clock3, Flag, PenLine, RefreshCw, Sparkles, WifiOff } from "lucide-react";

import type { Me, QueuePatient } from "@/api/contract";
import { ColourChip } from "@/components/afya/colour-chip";
import { NoticeCallout, NoticeChip } from "@/components/afya/notice-chip";
import { useQueue } from "@/lib/queries";
import { SATS } from "@/lib/sats";
import { ago, clockShort, mmss, useNow } from "@/lib/time";
import { cn } from "@/lib/utils";

/** Seconds left to the SATS time-to-be-seen target (negative = over). null = no target. */
export function secondsLeft(p: QueuePatient, now: number): number | null {
  if (p.target_minutes === null) return null;
  return p.target_minutes * 60 - (now - Date.parse(p.arrived_at)) / 1000;
}

function sortByTimeLeft(ps: QueuePatient[], now: number): QueuePatient[] {
  return [...ps].sort((a, b) => {
    const la = secondsLeft(a, now);
    const lb = secondsLeft(b, now);
    if (la === null && lb === null) return Date.parse(a.arrived_at) - Date.parse(b.arrived_at);
    if (la === null) return 1;
    if (lb === null) return -1;
    return la - lb;
  });
}

export function Board({
  me,
  onOpen,
  onRecord,
  openVisit,
}: {
  me: Me;
  onOpen: (visitId: string) => void;
  onRecord: (p: QueuePatient) => void;
  openVisit: string | null;
}) {
  const q = useQueue();
  const now = useNow(1000);
  const canWrite = me.role !== "manager";

  const patients = q.data ? sortByTimeLeft(q.data.patients, now) : [];
  const over = patients.filter((p) => (secondsLeft(p, now) ?? 1) < 0).length;
  const reviews = patients.reduce((n, p) => n + p.pending_proposals, 0);

  return (
    <section aria-labelledby="board-title" className="animate-rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 id="board-title" className="font-display text-4xl tracking-tight">
            Waiting room
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sorted by time left to the SATS target of each patient&apos;s confirmed colour.
          </p>
        </div>
        <LiveStatus updatedAt={q.dataUpdatedAt} failed={q.isError} fetching={q.isFetching} now={Date.now()} />
      </div>

      <dl className="mt-5 grid grid-cols-3 gap-3 sm:max-w-xl">
        <Stat label="Waiting" value={q.data ? patients.length : "–"} />
        <Stat label="Over target" value={q.data ? over : "–"} tone={over > 0 ? "red" : undefined} />
        <Stat label="Second looks to review" value={q.data ? reviews : "–"} tone={reviews > 0 ? "agent" : undefined} />
      </dl>

      {q.data?.notices.map((n, i) => (
        <NoticeCallout key={`${n.code}-${i}`} code={n.code} className="mt-4" />
      ))}

      <div className="mt-6 overflow-hidden rounded-2xl border bg-card shadow-[0_1px_2px_oklch(0_0_0/0.04)]">
        <div className="hidden grid-cols-[150px_minmax(140px,1fr)_minmax(220px,1.6fr)_150px_150px_130px] gap-4 border-b bg-muted/50 px-5 py-2.5 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase lg:grid">
          <span>Confirmed colour</span>
          <span>Patient</span>
          <span>Time to target</span>
          <span>Last reading</span>
          <span>Re-check</span>
          <span className="sr-only">Actions</span>
        </div>
        {q.isPending && <SkeletonRows />}
        {q.isError && !q.data && (
          <p className="p-8 text-center text-sm text-muted-foreground">Can&apos;t load the waiting room. Retrying…</p>
        )}
        {q.data && patients.length === 0 && (
          <div className="p-12 text-center">
            <p className="font-display text-2xl">The waiting room is empty.</p>
            <p className="mt-1 text-sm text-muted-foreground">New patients appear here after triage.</p>
          </div>
        )}
        <ul role="list" className="divide-y">
          {patients.map((p) => (
            <PatientRow
              key={p.visit_id}
              p={p}
              now={now}
              canWrite={canWrite}
              selected={openVisit === p.visit_id}
              onOpen={() => onOpen(p.visit_id)}
              onRecord={() => onRecord(p)}
            />
          ))}
        </ul>
      </div>
      {q.data && (
        <p className="mt-3 text-xs text-muted-foreground">
          Re-check intervals are a {q.data.site_rule_source}. Synthetic patients only.
        </p>
      )}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "red" | "agent" }) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card px-4 py-3",
        tone === "red" && "border-sats-red/30 bg-sats-red-soft",
        tone === "agent" && "border-agent/30 bg-agent-soft",
      )}
    >
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "tnum mt-0.5 text-2xl font-semibold",
          tone === "red" && "text-sats-red-ink",
          tone === "agent" && "text-agent-foreground",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function LiveStatus({ updatedAt, failed, fetching, now }: { updatedAt: number; failed: boolean; fetching: boolean; now: number }) {
  if (failed) {
    return (
      <p role="status" className="inline-flex items-center gap-2 rounded-full border border-warn/40 bg-warn-soft px-3 py-1.5 text-sm">
        <WifiOff className="size-4" /> Connection lost · retrying
        {updatedAt > 0 && <span className="text-muted-foreground">· last data {ago(updatedAt, now)}</span>}
      </p>
    );
  }
  return (
    <p role="status" data-testid="live" className="inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm text-muted-foreground">
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok opacity-50" />
        <span className="relative inline-flex size-2 rounded-full bg-ok" />
      </span>
      <span className="font-medium text-foreground">Live</span>
      {updatedAt > 0 ? <span className="tnum">· updated {ago(updatedAt, now)}</span> : <span>· connecting…</span>}
      <RefreshCw className={cn("size-3.5 transition-opacity", fetching ? "animate-spin opacity-70" : "opacity-0")} />
    </p>
  );
}

function SkeletonRows() {
  return (
    <div className="divide-y">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex items-center gap-4 px-5 py-5">
          <div className="h-7 w-24 animate-pulse rounded-lg bg-muted" />
          <div className="h-5 w-20 animate-pulse rounded bg-muted" />
          <div className="h-3 flex-1 animate-pulse rounded-full bg-muted" />
        </div>
      ))}
    </div>
  );
}

export function TargetBar({ p, now, compact = false }: { p: QueuePatient; now: number; compact?: boolean }) {
  const left = secondsLeft(p, now);
  if (left === null || !p.confirmed_colour) {
    return (
      <div className="text-sm text-muted-foreground">
        <span className="font-medium">No target</span>
        <span className="block text-xs">{p.confirmed_colour ? "No chart for this patient" : "No confirmed colour yet"}</span>
      </div>
    );
  }
  const total = (p.target_minutes ?? 0) * 60;
  const waited = total - left;
  const isOver = left < 0;
  const frac = total === 0 ? 1 : Math.min(1, waited / total);
  const m = SATS[p.confirmed_colour];
  const urgent = !isOver && total > 0 && left < Math.min(total * 0.2, 600);
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        {p.target_minutes === 0 ? (
          <span className="text-sm font-semibold text-sats-red-ink">Immediate</span>
        ) : isOver ? (
          <span data-testid="over" className="tnum text-sm font-semibold text-sats-red-ink">
            +{mmss(-left)} over
          </span>
        ) : (
          <span className={cn("tnum text-sm font-semibold", urgent && "text-sats-orange-ink")}>{mmss(left)} left</span>
        )}
        {!compact && (
          <span className="tnum text-xs text-muted-foreground">
            {Math.floor(waited / 60)} / {p.target_minutes} min
          </span>
        )}
      </div>
      <div
        className="relative mt-1.5 h-2.5 overflow-hidden rounded-full bg-muted"
        role="meter"
        aria-label="Time waited against the SATS target"
        aria-valuemin={0}
        aria-valuemax={p.target_minutes ?? 0}
        aria-valuenow={Math.floor(waited / 60)}
      >
        {isOver || total === 0 ? (
          <div className="stripes-over absolute inset-0 animate-[pulse_2.4s_ease-in-out_infinite]" />
        ) : (
          <div className={cn("absolute inset-y-0 left-0 rounded-full transition-[width] duration-1000 ease-linear", m.bg)} style={{ width: `${frac * 100}%` }} />
        )}
      </div>
    </div>
  );
}

function Recheck({ p, now }: { p: QueuePatient; now: number }) {
  if (!p.recheck) return <span className="text-sm text-muted-foreground">–</span>;
  const dueIn = (Date.parse(p.recheck.due_at) - now) / 1000;
  const overdue = dueIn < 0;
  return (
    <div className="text-sm">
      <span className={cn("tnum inline-flex items-center gap-1 font-medium", overdue && "text-[color-mix(in_oklch,var(--warn),black_30%)] dark:text-warn")}>
        <Clock3 className="size-3.5" />
        {overdue ? `Overdue ${mmss(-dueIn)}` : `In ${mmss(dueIn)}`}
      </span>
      <span className="block text-xs text-muted-foreground">every {p.recheck.interval_minutes} min · site rule</span>
    </div>
  );
}

function PatientRow({
  p,
  now,
  canWrite,
  selected,
  onOpen,
  onRecord,
}: {
  p: QueuePatient;
  now: number;
  canWrite: boolean;
  selected: boolean;
  onOpen: () => void;
  onRecord: () => void;
}) {
  const proposal = p.pending_proposals > 0;
  return (
    <li
      data-testid={`row-${p.visit_id}`}
      className={cn(
        "group relative grid cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-3 px-4 py-4 transition-colors sm:px-5",
        "lg:grid-cols-[150px_minmax(140px,1fr)_minmax(220px,1.6fr)_150px_150px_130px]",
        "hover:bg-muted/40",
        selected && "bg-muted/60",
        proposal && "bg-agent-soft/40 hover:bg-agent-soft/60",
      )}
      onClick={onOpen}
    >
      {proposal && <span aria-hidden className="absolute inset-y-0 left-0 w-1 bg-agent" />}
      <div>
        <ColourChip colour={p.confirmed_colour} />
      </div>

      <div className="min-w-0">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
          className="font-mono text-lg font-semibold tracking-tight outline-none hover:underline focus-visible:underline"
        >
          {p.patient_label}
        </button>
        <p className="tnum text-xs text-muted-foreground">
          Arrived {clockShort(p.arrived_at)} · waited {Math.floor((now - Date.parse(p.arrived_at)) / 60000)} min
        </p>
      </div>

      <div className="col-span-3 row-start-2 lg:col-span-1 lg:row-start-auto">
        <TargetBar p={p} now={now} />
        <p className="tnum mt-1.5 text-xs text-muted-foreground lg:hidden">
          {p.last_reading ? `Last reading TEWS ${p.last_reading.tews}, ${ago(Date.parse(p.last_reading.effective), now)}` : "No reading yet"}
          {p.recheck &&
            (Date.parse(p.recheck.due_at) < now
              ? ` · re-check overdue ${mmss((now - Date.parse(p.recheck.due_at)) / 1000)}`
              : ` · re-check in ${mmss((Date.parse(p.recheck.due_at) - now) / 1000)}`)}
        </p>
      </div>

      <div className="hidden text-sm lg:block">
        {p.last_reading ? (
          <>
            <span className="inline-flex items-center gap-1.5 font-medium">
              <Activity className="size-3.5 text-muted-foreground" />
              TEWS <span className="tnum">{p.last_reading.tews}</span>
              <span aria-label={SATS[p.last_reading.colour].label} className={cn("text-xs", SATS[p.last_reading.colour].ink)}>
                {SATS[p.last_reading.colour].shape}
              </span>
            </span>
            <span className="tnum block text-xs text-muted-foreground">{ago(Date.parse(p.last_reading.effective), now)}</span>
          </>
        ) : (
          <span className="text-muted-foreground">No reading yet</span>
        )}
      </div>

      <div className="hidden lg:block">
        <Recheck p={p} now={now} />
      </div>

      <div className="col-start-3 row-start-1 flex items-center justify-end gap-1 lg:col-start-auto lg:row-start-auto">
        {canWrite && (
          <button
            type="button"
            data-testid={`record-${p.visit_id}`}
            onClick={(e) => {
              e.stopPropagation();
              onRecord();
            }}
            className="inline-flex h-11 items-center gap-1.5 rounded-xl border bg-background px-3 text-sm font-medium hover:bg-card hover:shadow-sm"
          >
            <PenLine className="size-4" /> Vitals
          </button>
        )}
        <ChevronRight className="size-5 text-muted-foreground transition group-hover:translate-x-0.5" />
      </div>

      {(proposal || p.flags.length > 0 || p.notices.length > 0) && (
        <div className="col-span-3 flex flex-wrap items-center gap-1.5 lg:col-span-5 lg:col-start-2 lg:-mt-1">
          {proposal && (
            <span className="inline-flex h-6 items-center gap-1 rounded-full bg-agent px-2.5 text-[11px] font-semibold text-white animate-pulse-ring">
              <Sparkles className="size-3.5" />
              Second look suggested{canWrite && " · review"}
            </span>
          )}
          {p.flags.includes("second_look") && (
            <span className="inline-flex h-6 items-center gap-1 rounded-full border border-foreground/15 bg-background px-2 text-[11px] font-semibold">
              <Flag className="size-3.5" /> Second look confirmed
            </span>
          )}
          {p.notices.map((n, i) => (
            <NoticeChip key={`${n.code}-${i}`} notice={n} />
          ))}
        </div>
      )}
    </li>
  );
}
