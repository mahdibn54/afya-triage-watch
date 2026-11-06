"use client";

import type { Sign } from "@/api/contract";
import { SATS } from "@/lib/sats";
import { cn } from "@/lib/utils";

/** Why a mention does not count, in plain words. */
export const OTHER_REASON: Record<string, string> = {
  not_current: "not current",
  negated: "denied by the patient",
  third_party: "about someone else",
  historical: "in the past",
  hypothetical: "only a worry",
};
export function reasonText(r: string | null): string {
  if (!r) return "does not count";
  return OTHER_REASON[r] ?? r.replace(/_/g, " ");
}

type Segment = { text: string; sign: Sign | null };

/**
 * Splits the complaint into plain-text segments around each sign's quote_span.
 * Offsets are Unicode code points of the original complaint (docs/api.md section 1), so slice with Array.from.
 * Spans that are out of range or that overlap an earlier one are ignored (the text is still shown in full).
 */
export function segments(complaint: string, signs: Sign[]): Segment[] {
  const chars = Array.from(complaint);
  const spans = signs
    .filter((s) => s.source === "complaint" && s.quote_span)
    .filter((s) => s.quote_span!.start >= 0 && s.quote_span!.end <= chars.length && s.quote_span!.start < s.quote_span!.end)
    .sort((a, b) => a.quote_span!.start - b.quote_span!.start);
  const out: Segment[] = [];
  let at = 0;
  for (const s of spans) {
    const { start, end } = s.quote_span!;
    if (start < at) continue;
    if (start > at) out.push({ text: chars.slice(at, start).join(""), sign: null });
    out.push({ text: chars.slice(start, end).join(""), sign: s });
    at = end;
  }
  if (at < chars.length) out.push({ text: chars.slice(at).join(""), sign: null });
  return out;
}

/** The patient's words, rendered as text nodes only (never HTML), with matched phrases highlighted. */
export function Complaint({
  complaint,
  signs,
  active,
  onActive,
}: {
  complaint: string;
  signs: Sign[];
  active: string | null;
  onActive: (code: string | null) => void;
}) {
  return (
    <blockquote data-testid="complaint" className="font-display text-[1.6rem] leading-snug text-pretty">
      <span aria-hidden className="mr-1 text-muted-foreground/60">“</span>
      {segments(complaint, signs).map((seg, i) => {
        if (!seg.sign) return <span key={i}>{seg.text}</span>;
        const s = seg.sign;
        const current = s.status === "current";
        const m = SATS[s.colour];
        return (
          <mark
            key={i}
            tabIndex={0}
            data-sign={s.code}
            data-status={s.status}
            onMouseEnter={() => onActive(s.code)}
            onMouseLeave={() => onActive(null)}
            onFocus={() => onActive(s.code)}
            onBlur={() => onActive(null)}
            title={current ? `${s.gloss} (${m.label})` : `${s.gloss}: ${reasonText(s.reason)}`}
            className={cn(
              "rounded-md px-1 py-0.5 text-inherit outline-none transition-all box-decoration-clone",
              current
                ? cn(m.soft, "underline decoration-2 underline-offset-[5px]", s.colour === "RED" && "decoration-sats-red", s.colour === "ORANGE" && "decoration-sats-orange", s.colour === "YELLOW" && "decoration-sats-yellow", s.colour === "GREEN" && "decoration-sats-green")
                : "bg-muted text-muted-foreground line-through decoration-muted-foreground/50 decoration-1",
              active === s.code && "ring-2 ring-agent ring-offset-1 ring-offset-card",
            )}
          >
            {seg.text}
          </mark>
        );
      })}
      <span aria-hidden className="ml-0.5 text-muted-foreground/60">”</span>
    </blockquote>
  );
}
