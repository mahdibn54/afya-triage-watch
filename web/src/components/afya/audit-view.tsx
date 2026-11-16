"use client";

import { Bot, ShieldCheck, User } from "lucide-react";
import { useState } from "react";

import type { AuditRow } from "@/api/contract";
import { fullName } from "@/lib/identity";
import { caseRef } from "@/components/afya/patient-name";
import { useAudit, useQueue, useUserName } from "@/lib/queries";
import { clock } from "@/lib/time";
import { cn } from "@/lib/utils";

const KIND: Record<string, { text: string; tone?: "ok" | "bad" | "agent" }> = {
  login: { text: "Signed in (demo switcher)" },
  logout: { text: "Signed out" },
  vitals_recorded: { text: "Recorded vitals" },
  vitals_refused: { text: "Vitals refused: re-measure", tone: "bad" },
  proposal_created: { text: "Suggested a second look", tone: "agent" },
  proposal_approved: { text: "Confirmed a suggestion", tone: "ok" },
  proposal_rejected: { text: "Rejected a suggestion" },
  proposal_acknowledged: { text: "Marked a suggestion as seen" },
  approve_refused: { text: "Confirm refused", tone: "bad" },
  reject_refused: { text: "Reject refused", tone: "bad" },
  command_done: { text: "Flag and colour written to the record", tone: "ok" },
  command_abandoned: { text: "Confirmed flag was not recorded", tone: "bad" },
  notification_acknowledged: { text: "Dismissed a notice" },
  agent_step: { text: "Agent step", tone: "agent" },
  record_vitals: { text: "Tool: record vitals" },
  compute_tews: { text: "Tool: compute the score", tone: "agent" },
  check_deterioration: { text: "Tool: compare readings", tone: "agent" },
  get_queue_state: { text: "Tool: read the waiting room", tone: "agent" },
  raise_recheck_flag: { text: "Tool: raise the second-look flag", tone: "ok" },
  notify_staff: { text: "Tool: remind staff", tone: "agent" },
  seed_demo_visit: { text: "Demo: scenario loaded" },
};

function describe(r: AuditRow): string {
  const k = KIND[r.kind]?.text ?? r.kind.replace(/_/g, " ");
  const p = r.payload;
  const bits: string[] = [];
  if (typeof p.colour === "string") bits.push(String(p.colour));
  if (typeof p.to_colour === "string") bits.push(`to ${p.to_colour}`);
  if (p.reason === "role") bits.push("not a nurse or clinician");
  if (p.reason === "not_pending" || p.reason === "not pending") bits.push("no longer pending");
  if (p.reason === "invalid") bits.push("the request was not valid");
  if (typeof p.name === "string" && r.kind === "agent_step") bits.push(String(p.name));
  if (p.override === true) bits.push("colour overridden with a reason");
  return bits.length ? `${k} · ${bits.join(" · ")}` : k;
}

/** Read-only audit viewer. Payloads hold ids, codes and numbers only (never free text). */
export function AuditView() {
  const [visit, setVisit] = useState<string>("");
  const [history, setHistory] = useState(false);
  const audit = useAudit({ visit_id: visit || undefined, limit: 200, since_reset: !history });
  const queue = useQueue();
  const who = (visitId: string | null | undefined) => {
    const p = queue.data?.patients.find((x) => x.visit_id === visitId);
    if (!p) return null;
    return { name: fullName(p), file: [p.file_number, caseRef(p)].filter(Boolean).join(" · ") };
  };
  const name = useUserName();

  return (
    <section aria-labelledby="audit-title" className="animate-rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 id="audit-title" className="font-display text-4xl tracking-tight">
            Audit log
          </h1>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
            <ShieldCheck className="size-4" /> Every action by people and by the agent, newest first. Append-only: nobody can edit it.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            data-testid="audit-history"
            checked={history}
            onChange={(e) => setHistory(e.target.checked)}
            className="size-4"
          />
          <span className="text-muted-foreground">Show full history</span>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-muted-foreground">Patient</span>
          <select
            value={visit}
            onChange={(e) => setVisit(e.target.value)}
            className="h-11 rounded-xl border bg-card px-3 font-medium"
          >
            <option value="">All</option>
            {queue.data?.patients.map((p) => (
              <option key={p.visit_id} value={p.visit_id}>
                {fullName(p)}{p.file_number ? ` · ${p.file_number}` : ""}
              </option>
            ))}
          </select>
        </label>
        </div>
      </div>
      {!history && (
        <p className="mt-3 text-xs text-muted-foreground">
          Showing entries since the last demo reset. Older entries are kept, never deleted: tick “Show full history” to see them.
        </p>
      )}

      <div className="mt-6 overflow-x-auto rounded-2xl border bg-card">
        <table data-testid="audit" className="w-full min-w-[760px] text-sm">
          <thead className="bg-muted/50 text-left text-2xs font-semibold tracking-wider text-muted-foreground uppercase">
            <tr>
              <th className="px-4 py-2.5">Time</th>
              <th className="px-4 py-2.5">Who</th>
              <th className="px-4 py-2.5">What</th>
              <th className="px-4 py-2.5">Patient</th>
              <th className="px-4 py-2.5">Records</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {audit.isPending &&
              [0, 1, 2, 3].map((i) => (
                <tr key={i}>
                  <td colSpan={5} className="px-4 py-3">
                    <div className="h-5 animate-pulse rounded bg-muted" />
                  </td>
                </tr>
              ))}
            {audit.data?.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-muted-foreground">
                  Nothing logged yet.
                </td>
              </tr>
            )}
            {audit.data?.map((r) => {
              const tone = KIND[r.kind]?.tone;
              const machine = r.actor === "agent" || r.actor === "system";
              const patient = who(r.visit_id);
              const ids = Object.entries(r.payload)
                .filter(([k, v]) => typeof v === "string" && (k.endsWith("_id") || k === "obs_id"))
                .map(([k, v]) => [k, String(v)] as const);
              return (
                <tr key={r.id} data-kind={r.kind}>
                  <td className="tnum px-4 py-2.5 font-mono text-xs text-muted-foreground">{clock(r.at)}</td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center gap-1.5 font-medium">
                      {machine ? <Bot className="size-4 text-agent" /> : <User className="size-4 text-muted-foreground" />}
                      {name(r.actor)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={cn(
                        "font-medium",
                        tone === "ok" && "text-ok",
                        tone === "bad" && "text-destructive",
                        tone === "agent" && "text-agent-foreground",
                      )}
                    >
                      {describe(r)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {patient ? (
                      <span className="leading-tight">
                        <span className="block font-medium">{patient.name}</span>
                        <span className="block font-mono text-2xs text-muted-foreground">{patient.file}</span>
                      </span>
                    ) : (
                      <span className="font-mono text-xs text-muted-foreground">{r.visit_id ? `visit ${r.visit_id}` : "–"}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="flex flex-wrap gap-1">
                      {ids.map(([k, v]) => (
                        <code key={k} title={k} className="rounded bg-muted px-1.5 py-0.5 font-mono text-2xs text-muted-foreground">
                          {v.length > 20 ? `${v.slice(0, 8)}…` : v}
                        </code>
                      ))}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
