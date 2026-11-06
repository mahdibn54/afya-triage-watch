"use client";

import { ArrowRight, Ban, Check, Eye, Loader2, Lock, Quote, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import type { Colour, Me, Proposal } from "@/api/contract";
import { ColourChip } from "@/components/afya/colour-chip";
import { Complaint, reasonText } from "@/components/afya/complaint";
import { EvidenceTable } from "@/components/afya/evidence";
import { GateSteps } from "@/components/afya/gate-steps";
import { NoticeCallout } from "@/components/afya/notice-chip";
import { Checkbox } from "@/components/ui/checkbox";
import { ApiError } from "@/lib/api";
import { useApprove, useReject } from "@/lib/queries";
import { COLOURS, INPUT_LABEL, SATS } from "@/lib/sats";
import { ago, useClientNow } from "@/lib/time";
import { cn } from "@/lib/utils";

const TRIGGER: Record<string, string> = {
  colour_rise: "Colour rise",
  sign: "SATS sign in the complaint",
  nurse_reported: "Patient or nurse reports worse",
};

const ACTION: Record<NonNullable<Proposal["agent_action"]>, string> = {
  propose: "Asks for a second look",
  propose_and_remeasure: "Asks for a second look and a re-measure",
  request_missing_value: "Asks for a missing value",
};

function decisionError(e: unknown): { title: string; body: string } {
  if (e instanceof ApiError && e.status === 403)
    return { title: "Not allowed for your role", body: "Only a nurse or clinician can decide. This attempt was written to the audit log." };
  if (e instanceof ApiError && e.status === 409)
    return { title: "Already decided", body: "Someone else decided this suggestion, or a newer reading replaced it. The card now shows the latest state." };
  if (e instanceof ApiError && e.code === "invalid") return { title: "Check the form", body: e.message };
  return { title: "Not sent", body: `${e instanceof Error ? e.message : "Unknown error"} Nothing was changed; you can try again.` };
}

export function ApprovalCard({ me, proposal }: { me: Me; proposal: Proposal }) {
  const p = proposal;
  const now = useClientNow(15_000);
  const canDecide = me.role === "nurse" || me.role === "clinician";
  const currentSigns = p.signs.filter((s) => s.status === "current");
  const otherSigns = p.signs.filter((s) => s.status === "other");

  const [active, setActive] = useState<string | null>(null);
  const [kept, setKept] = useState<Set<string>>(() => new Set(currentSigns.map((s) => s.code)));
  const [colour, setColour] = useState<Colour>(p.proposed_colour);
  const [overrideReason, setOverrideReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const approve = useApprove(p.id);
  const reject = useReject(p.id);
  const overriding = colour !== p.proposed_colour;
  const lower = SATS[colour].rank < SATS[p.proposed_colour].rank;
  const busy = approve.isPending || reject.isPending;
  const error = approve.error ?? reject.error;

  function onApprove() {
    approve.mutate(
      { colour, signs_kept: [...kept], override_reason: overriding ? overrideReason.trim() : null },
      {
        onSuccess: () =>
          toast.success(`Confirmed ${SATS[colour].label} ${SATS[colour].shape} for ${p.patient_label ?? p.visit_id}`, {
            description: "The flag and colour are being written to the record.",
          }),
        onError: (e) => toast.error(decisionError(e).title, { description: decisionError(e).body, duration: 8000 }),
      },
    );
  }
  function onReject() {
    reject.mutate(rejectReason.trim(), {
      onSuccess: () => toast(`Suggestion for ${p.patient_label ?? p.visit_id} rejected`, { description: "Logged with your reason. The colour stays as it was." }),
      onError: (e) => toast.error(decisionError(e).title, { description: decisionError(e).body, duration: 8000 }),
    });
  }

  return (
    <article
      data-testid="approval-card"
      className="animate-rise overflow-hidden rounded-2xl border border-agent/35 bg-card shadow-[0_18px_50px_-30px_color-mix(in_oklch,var(--agent),transparent_30%)]"
    >
      {/* Header: what the agent suggests, never what it decided */}
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-agent-soft px-5 py-3 text-agent-foreground">
        <span className="grid size-7 place-items-center rounded-lg bg-agent text-white">
          <Sparkles className="size-4" />
        </span>
        <p className="font-semibold">Second look suggested</p>
        <p className="text-sm opacity-80">
          by the watch agent · {ago(Date.parse(p.created_at), now)} · {TRIGGER[p.trigger] ?? p.trigger}
        </p>
        <p className="ml-auto inline-flex items-center gap-1 text-xs font-medium">
          <Lock className="size-3.5" /> Nothing changes until a nurse confirms
        </p>
      </header>

      <div className="space-y-6 p-5 sm:p-6">
        {/* Current → proposed */}
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Confirmed now</p>
            <ColourChip colour={p.current_colour} size="lg" muted />
          </div>
          <ArrowRight className="mt-5 size-6 text-muted-foreground" />
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Suggested</p>
            <ColourChip colour={p.proposed_colour} size="lg" />
          </div>
          <div className="ml-auto text-right">
            <p className="text-xs font-medium text-muted-foreground">TEWS</p>
            <p className="tnum text-3xl font-semibold">
              <span className="text-muted-foreground">{p.tews_before ?? "–"}</span>
              <span className="mx-1.5 text-xl text-muted-foreground">→</span>
              {p.tews_after ?? "–"}
            </p>
          </div>
        </div>

        {/* Why: code-built reasons, then the model's note if it passed the wording filter */}
        <div className="space-y-2">
          <ul className="space-y-1">
            {p.reasons.map((r) => (
              // reasons are code-built ("colour rise YELLOW -> ORANGE (TEWS 6)"): capitalise for reading
              <li key={r} className="flex items-start gap-2 text-[15px] font-medium">
                <Check className="mt-0.5 size-4 shrink-0 text-agent" />
                {r.charAt(0).toUpperCase() + r.slice(1).replace("->", "→")}
              </li>
            ))}
          </ul>
          {p.rationale && (
            <div className="rounded-xl bg-muted/60 p-3.5">
              <p className="text-[15px] leading-relaxed">{p.rationale}</p>
              <p className="mt-1.5 text-xs text-muted-foreground">
                {p.rationale_source === "model"
                  ? "Agent's note · passed the wording check (no condition, cause or treatment words)"
                  : "Written by fixed code from the cited readings"}
                {p.agent_action && ` · ${ACTION[p.agent_action]}`}
                {p.missing_input && `: ${INPUT_LABEL[p.missing_input] ?? p.missing_input}`}
              </p>
            </div>
          )}
        </div>

        {p.notices.map((n, i) => (
          <NoticeCallout key={`${n.code}-${i}`} code={n.code} />
        ))}

        <EvidenceTable rows={p.evidence} />

        {/* The patient's words */}
        {p.complaint && (
          <section aria-labelledby={`complaint-${p.id}`}>
            <h3 id={`complaint-${p.id}`} className="mb-2 flex items-center gap-1.5 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
              <Quote className="size-3.5" /> Patient&apos;s words
            </h3>
            <Complaint complaint={p.complaint} signs={p.signs} active={active} onActive={setActive} />
            {p.signs_verdict === null && (
              <p className="mt-2 text-xs text-muted-foreground">Phrases were not matched: the language model was offline.</p>
            )}
            {p.signs_verdict === "unsure" && (
              <p className="mt-2 text-xs text-muted-foreground">The sign matcher was unsure: please read the complaint yourself.</p>
            )}
          </section>
        )}

        {/* Signs: current ones can be unticked; other mentions are shown greyed with the reason */}
        {(currentSigns.length > 0 || otherSigns.length > 0) && (
          <section aria-labelledby={`signs-${p.id}`}>
            <h3 id={`signs-${p.id}`} className="mb-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
              SATS signs {canDecide && currentSigns.length > 0 && <span className="font-normal normal-case">· untick any you disagree with</span>}
            </h3>
            <ul className="space-y-2">
              {currentSigns.map((s) => (
                <li
                  key={s.code}
                  onMouseEnter={() => setActive(s.code)}
                  onMouseLeave={() => setActive(null)}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border p-3 transition",
                    active === s.code && "border-agent ring-2 ring-agent/30",
                    !kept.has(s.code) && "opacity-60",
                  )}
                >
                  {canDecide && (
                    <Checkbox
                      data-testid={`sign-${s.code}`}
                      checked={kept.has(s.code)}
                      onCheckedChange={(v) =>
                        setKept((k) => {
                          const n = new Set(k);
                          if (v) n.add(s.code);
                          else n.delete(s.code);
                          return n;
                        })
                      }
                      className="size-6"
                      aria-label={`Keep sign: ${s.gloss}`}
                    />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium first-letter:uppercase">{s.gloss}</span>
                    <span className="block text-sm text-muted-foreground">
                      {s.source === "reading" ? "from the reading" : <>“{s.quote}”</>}
                    </span>
                  </span>
                  <ColourChip colour={s.colour} size="sm" />
                </li>
              ))}
              {otherSigns.map((s) => (
                <li
                  key={s.code}
                  onMouseEnter={() => setActive(s.code)}
                  onMouseLeave={() => setActive(null)}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border border-dashed p-3 text-muted-foreground transition",
                    active === s.code && "border-agent",
                  )}
                >
                  <Ban className="size-5 shrink-0 opacity-60" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium first-letter:uppercase">{s.gloss}</span>
                    <span className="block text-sm">
                      “{s.quote}” · <span className="font-medium">does not count: {reasonText(s.reason)}</span>
                    </span>
                  </span>
                  <ColourChip colour={s.colour} size="sm" muted className="opacity-60" />
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <section aria-label="Safety gates" className="border-t px-5 py-4 sm:px-6">
        <h3 className="mb-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Safety gates</h3>
        <GateSteps proposalId={p.id} />
      </section>

      {/* Decision */}
      {canDecide ? (
        <footer className="space-y-4 border-t bg-muted/30 p-5 sm:p-6">
          <fieldset>
            <legend className="mb-2 text-sm font-semibold">Colour to confirm</legend>
            <div role="radiogroup" className="flex flex-wrap gap-2">
              {COLOURS.map((c) => {
                const on = colour === c;
                return (
                  <button
                    key={c}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    data-testid={`colour-${c}`}
                    onClick={() => setColour(c)}
                    className={cn(
                      "flex h-12 items-center gap-2 rounded-xl border bg-background px-3 text-sm font-semibold transition",
                      on && cn("ring-2 ring-offset-2 ring-offset-background", SATS[c].ring),
                    )}
                  >
                    <ColourChip colour={c} size="sm" />
                    {c === p.proposed_colour && <span className="text-xs font-normal text-muted-foreground">suggested</span>}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {overriding && (
            <label className="block animate-rise">
              <span className="text-sm font-semibold">
                Reason for choosing {SATS[colour].label} instead of {SATS[p.proposed_colour].label}{" "}
                <span className="font-normal text-destructive">required</span>
              </span>
              {lower && (
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  This is lower than the suggestion. Your reason is kept in the audit log.
                </span>
              )}
              <textarea
                data-testid="override-reason"
                rows={2}
                maxLength={300}
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                className="mt-1.5 block w-full rounded-xl border bg-background px-3 py-2 text-base outline-none focus:ring-3 focus:ring-ring/30"
              />
            </label>
          )}

          {error && (
            <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm">
              <p className="font-semibold text-destructive">{decisionError(error).title}</p>
              <p className="mt-0.5 text-muted-foreground">{decisionError(error).body}</p>
            </div>
          )}

          {rejecting ? (
            <div className="animate-rise space-y-2 rounded-xl border bg-background p-4">
              <label className="block">
                <span className="text-sm font-semibold">Why reject this suggestion?</span>
                <span className="block text-xs text-muted-foreground">Plain words; kept in the audit log. The colour stays {p.current_colour ? SATS[p.current_colour].label : "as it is"}.</span>
                <textarea
                  data-testid="reject-reason"
                  autoFocus
                  rows={2}
                  maxLength={300}
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="e.g. Re-measured at the desk; the readings were a cuff error."
                  className="mt-1.5 block w-full rounded-xl border bg-background px-3 py-2 text-base outline-none focus:ring-3 focus:ring-ring/30"
                />
              </label>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setRejecting(false)} className="h-11 rounded-xl px-4 text-sm font-medium hover:bg-muted">
                  Back
                </button>
                <button
                  type="button"
                  data-testid="reject-confirm"
                  disabled={!rejectReason.trim() || busy}
                  onClick={onReject}
                  className="inline-flex h-11 items-center gap-2 rounded-xl border border-destructive/40 px-4 text-sm font-semibold text-destructive hover:bg-destructive/5 disabled:opacity-40"
                >
                  {reject.isPending ? <Loader2 className="size-4 animate-spin" /> : <X className="size-4" />}
                  Reject suggestion
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
              <button
                type="button"
                data-testid="reject"
                disabled={busy}
                onClick={() => setRejecting(true)}
                className="h-12 rounded-xl px-4 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                Reject…
              </button>
              <button
                type="button"
                data-testid="approve"
                disabled={busy || (overriding && !overrideReason.trim())}
                onClick={onApprove}
                className="inline-flex h-14 items-center justify-center gap-2.5 rounded-xl bg-primary px-6 text-base font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-40"
              >
                {approve.isPending ? <Loader2 className="size-5 animate-spin" /> : <Check className="size-5" />}
                Confirm {SATS[colour].label} {SATS[colour].shape} and flag for a second look
              </button>
            </div>
          )}
          <p className="text-center text-xs text-muted-foreground sm:text-right">
            Confirming as {me.name}. Your name and the time are written to the record and the audit log.
          </p>
        </footer>
      ) : (
        <footer data-testid="read-only" className="flex items-center gap-3 border-t bg-muted/30 px-5 py-4 text-sm text-muted-foreground sm:px-6">
          <Eye className="size-5 shrink-0" />
          <p>
            <span className="font-semibold text-foreground">Read only.</span> A nurse or clinician confirms or rejects this
            suggestion; as a manager you can follow it here and in the audit log.
          </p>
        </footer>
      )}
    </article>
  );
}
