import type { Colour } from "@/api/contract";
import { SATS } from "@/lib/sats";
import { cn } from "@/lib/utils";

/** A SATS colour, always with its label and shape (■ ▲ ● ○), never colour alone. */
export function ColourChip({
  colour,
  size = "md",
  className,
  muted = false,
}: {
  colour: Colour | null;
  size?: "sm" | "md" | "lg";
  className?: string;
  muted?: boolean;
}) {
  if (!colour) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border border-dashed px-2 py-0.5 text-xs font-medium text-muted-foreground",
          className,
        )}
      >
        Not triaged
      </span>
    );
  }
  const m = SATS[colour];
  return (
    <span
      data-colour={colour}
      className={cn(
        "inline-flex shrink-0 items-center font-semibold uppercase tracking-wide",
        muted ? cn(m.soft, m.ink) : cn(m.bg, m.text),
        size === "sm" && "h-6 gap-1 rounded-md px-1.5 text-[11px]",
        size === "md" && "h-7 gap-1.5 rounded-lg px-2.5 text-xs",
        size === "lg" && "h-10 gap-2 rounded-xl px-3.5 text-sm",
        className,
      )}
    >
      <span aria-hidden className={cn(size === "lg" ? "text-base" : "text-[0.95em]", "leading-none")}>
        {m.shape}
      </span>
      {m.label}
    </span>
  );
}
