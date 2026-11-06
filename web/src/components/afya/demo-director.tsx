"use client";

import { ChevronDown, Clapperboard, Loader2, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import type { Me } from "@/api/contract";
import { ApiError } from "@/lib/api";
import { DEMO_LABEL } from "@/components/afya/vitals-dialog";
import { useDemo, useQueue } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** W6 demo scenario loader (E7-9). Rendered only when the API says DEMO_MODE=1. */
export function DemoDirector({ me, onOpen }: { me: Me; onOpen: (visitId: string | null) => void }) {
  const { load, next } = useDemo();
  const queue = useQueue();
  const [open, setOpen] = useState(true);
  if (!me.demo) return null;

  const p014 = queue.data?.patients.find((p) => p.patient_label === DEMO_LABEL);
  const busy = load.isPending || next.isPending;

  return (
    <aside
      aria-label="Demo director"
      data-testid="demo-director"
      className="fixed right-4 bottom-4 z-40 w-[min(340px,calc(100vw-2rem))] overflow-hidden rounded-2xl border-2 border-dashed border-warn/70 bg-card/95 shadow-xl backdrop-blur"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 bg-warn-soft px-4 py-2.5 text-left text-sm font-semibold"
      >
        <Clapperboard className="size-4" />
        Demo director
        <span className="font-mono text-[10px] font-bold tracking-[0.18em] text-muted-foreground uppercase">demo only</span>
        <ChevronDown className={cn("ml-auto size-4 transition", !open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-2 p-3">
          <button
            type="button"
            data-testid="demo-load"
            disabled={busy}
            onClick={() =>
              load.mutate(undefined, {
                onSuccess: () => {
                  onOpen(null);
                  toast.success("P-014 scenario loaded", { description: "First reading: YELLOW. Next, add the reading that raises the score." });
                },
                onError: (e) => toast.error("Could not load the scenario", { description: e.message }),
              })
            }
            className="flex h-12 w-full items-center gap-3 rounded-xl border bg-background px-3 text-left text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            {load.isPending ? <Loader2 className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
            <span>
              1 · Load the P-014 scenario
              <span className="block text-xs font-normal text-muted-foreground">Resets the room; P-014 starts YELLOW</span>
            </span>
          </button>
          <button
            type="button"
            data-testid="demo-next"
            disabled={busy || !p014}
            onClick={() =>
              next.mutate(undefined, {
                onSuccess: () => {
                  onOpen(p014?.visit_id ?? null);
                  toast("New reading for P-014", { description: "Watch the agent re-score it, step by step." });
                },
                onError: (e) =>
                  toast.error(e instanceof ApiError && e.status === 409 ? "P-014 has no more readings" : "Could not add the reading", {
                    description: e instanceof ApiError && e.status === 409 ? "Load the scenario again to replay it." : e.message,
                  }),
              })
            }
            className="flex h-12 w-full items-center gap-3 rounded-xl bg-primary px-3 text-left text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {next.isPending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
            <span>
              2 · Add P-014&apos;s next reading
              <span className="block text-xs font-normal opacity-80">The one that raises the score to ORANGE</span>
            </span>
          </button>
          <p className="px-1 text-[11px] leading-snug text-muted-foreground">
            Synthetic patients only. For the video, lower WATCH_INTERVAL_SECONDS and the reminder time in .env.
          </p>
        </div>
      )}
    </aside>
  );
}
