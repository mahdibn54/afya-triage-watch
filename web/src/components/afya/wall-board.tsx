"use client";

import { ColourChip } from "@/components/afya/colour-chip";
import { NoticeCallout } from "@/components/afya/notice-chip";
import { secondsLeft, sortByTimeLeft, TargetBar } from "@/components/afya/board";
import { useQueue } from "@/lib/queries";
import { ago, useClientNow, useNow } from "@/lib/time";

/** A display-only view for a staff-only screen; all decisions remain on the board. */
export function WallBoard({ onExit }: { onExit: () => void }) {
  const q = useQueue();
  const now = useNow();
  const clientNow = useClientNow();
  const patients = q.data ? sortByTimeLeft(q.data.patients, now) : [];
  const recordsOffline = q.data?.notices.some((n) => n.code === "fhir_unavailable") ?? false;
  const stale = q.dataUpdatedAt > 0 && clientNow - q.dataUpdatedAt > 15_000;

  return (
    <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 sm:px-8 sm:py-8">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-5">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Afya Triage Watch · staff display</p>
          <h1 className="font-display text-4xl sm:text-5xl">Waiting room</h1>
          <p className="mt-2 text-base text-muted-foreground">Confirmed colours · sorted by time left · synthetic patients</p>
        </div>
        <button type="button" onClick={onExit} className="min-h-11 rounded-xl border bg-card px-4 font-semibold hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2">Exit wall mode</button>
      </header>

      <div role="status" className={`mt-4 rounded-xl border px-4 py-3 text-lg font-semibold ${q.isError || stale ? "border-warn/40 bg-warn-soft" : "bg-card"}`}>
        {q.isError ? "Connection lost · retrying" : stale ? "Data may be out of date · check the board" : q.dataUpdatedAt ? "Connected" : "Connecting…"}
        {q.dataUpdatedAt > 0 && <span className="ml-2 font-normal">· last updated {ago(q.dataUpdatedAt, clientNow)}</span>}
      </div>
      {q.data?.notices.map((n, i) => <NoticeCallout key={`${n.code}-${i}`} code={n.code} className="mt-3 text-base" />)}
      {q.data?.truncated && <p role="status" className="mt-3 rounded-xl border border-warn/40 bg-warn-soft p-4 font-semibold">The queue is incomplete. Check the waiting room in the patient record.</p>}

      {q.isPending && <p className="py-12 text-center text-xl">Loading the waiting room…</p>}
      {q.isError && !q.data && <p className="py-12 text-center text-xl">The waiting room could not be loaded.</p>}
      {q.data && !recordsOffline && patients.length === 0 && <p className="py-12 text-center text-xl">The waiting room is empty.</p>}
      {patients.length > 0 && (
        <section aria-label="Waiting patients" className="mt-5">
          <p className="mb-3 text-base text-muted-foreground">{patients.length} waiting · Scroll to see all patients</p>
          <ul className="divide-y overflow-hidden rounded-xl border bg-card">
            {patients.map((p) => (
              <li key={p.visit_id} className="grid gap-3 px-4 py-5 sm:grid-cols-[minmax(8rem,1fr)_minmax(9rem,1fr)_minmax(14rem,2fr)] sm:items-center sm:px-6">
                <div className="min-w-0">
                  <p className="break-all font-mono text-2xl font-semibold">{p.patient_label || "Label unavailable"}</p>
                  {p.pending_proposals > 0 && <p className="mt-1 font-semibold text-agent-foreground">Second look suggested · review on board</p>}
                  {p.flags.length > 0 && <p className="mt-1 font-semibold">Second-look flag recorded</p>}
                  {p.notices.length > 0 && <p className="mt-1 text-sm font-medium">Notice on board · review patient</p>}
                </div>
                <div><ColourChip colour={p.confirmed_colour} size="lg" /></div>
                <div className="[&_span]:text-lg" aria-label={`Time to target${secondsLeft(p, now) === null ? ": unavailable" : ""}`}><TargetBar p={p} now={now} /></div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
