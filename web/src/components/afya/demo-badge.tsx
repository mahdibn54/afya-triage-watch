import { cn } from "@/lib/utils";

/** Always visible next to "sign in as…": there is no real authentication in demo mode. */
export function DemoBadge({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <span
      data-testid="demo-badge"
      title="Demo mode: no real authentication, synthetic patients only"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border-2 border-dashed border-warn/70 bg-warn-soft font-mono font-bold tracking-[0.18em] text-[color-mix(in_oklch,var(--warn),black_35%)] uppercase dark:text-warn",
        compact ? "h-6 px-1.5 text-[10px]" : "h-7 px-2 text-[11px]",
        className,
      )}
    >
      Demo
      {!compact && <span className="font-sans font-medium tracking-normal normal-case opacity-80">· synthetic data</span>}
    </span>
  );
}
