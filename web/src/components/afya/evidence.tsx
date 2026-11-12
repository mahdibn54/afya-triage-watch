import { ArrowUpRight } from "lucide-react";

import type { EvidenceRow } from "@/api/contract";
import { formatValue, INPUT_LABEL, unitLabel } from "@/lib/sats";
import { cn } from "@/lib/utils";

/** The readings behind a suggestion (E7-4, W2 as a table): one row per input whose value changed. */
export function EvidenceTable({ rows }: { rows: EvidenceRow[] }) {
  if (rows.length === 0) return null;
  const moved = rows.filter((r) => r.band_changed).length;
  return (
    <section aria-labelledby="evidence-title">
      <h3 id="evidence-title" className="mb-2 flex items-baseline justify-between text-xs font-semibold tracking-wider text-muted-foreground uppercase">
        The readings behind it
        {moved > 0 && (
          <span className="font-normal normal-case">
            {moved} {moved === 1 ? "value" : "values"} moved into a higher score band
          </span>
        )}
      </h3>
      <div className="overflow-x-auto rounded-xl border">
        <table data-testid="evidence" className="w-full min-w-[520px] text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Vital sign</th>
              <th scope="col" className="px-3 py-2 font-medium">Previous → new</th>
              <th scope="col" className="px-3 py-2 text-center font-medium">Points</th>
              <th scope="col" className="px-3 py-2 font-medium">Records</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => {
              const unit = unitLabel(r.unit);
              return (
                <tr
                  key={r.input}
                  data-band-changed={r.band_changed || undefined}
                  className={cn(r.band_changed && "bg-sats-orange-soft/60 dark:bg-sats-orange-soft/40")}
                >
                  <th scope="row" className="px-3 py-2.5 text-left font-medium">
                    <span className="flex items-center gap-1.5">
                      {r.band_changed && <ArrowUpRight aria-label="moved into a higher band" className="size-4 text-sats-orange-ink" />}
                      {INPUT_LABEL[r.input] ?? r.input}
                    </span>
                  </th>
                  <td className="tnum px-3 py-2.5">
                    <span className="text-muted-foreground">{formatValue(r.before.value)}</span>
                    <span className="mx-1.5 text-muted-foreground">→</span>
                    <span className={cn("font-semibold", r.band_changed && "text-sats-orange-ink")}>{formatValue(r.after.value)}</span>
                    {unit && <span className="ml-1 text-xs text-muted-foreground">{unit}</span>}
                  </td>
                  <td className="tnum px-3 py-2.5 text-center">
                    <span className="text-muted-foreground">{r.before.points ?? "–"}</span>
                    <span className="mx-1 text-muted-foreground">→</span>
                    <span
                      className={cn(
                        "inline-grid min-w-6 place-items-center rounded-md px-1 font-semibold",
                        r.band_changed && "bg-sats-orange text-white",
                      )}
                    >
                      {r.after.points ?? "–"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-2xs leading-tight text-muted-foreground">
                    <span className="block" title="previous reading">{r.before.obs_id}</span>
                    <span className="block text-foreground" title="new reading">{r.after.obs_id}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">Points come from the fixed SATS rules, not from the language model.</p>
    </section>
  );
}
