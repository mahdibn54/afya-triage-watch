import { cn } from "@/lib/utils";

/** Mark: a calm pulse line that ends in a check. Reads as "watched, then confirmed". */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-8", className)}>
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M5 17h5l2.5-6 4 11 3-7.5L22 19l5-6"
        fill="none"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-primary-foreground"
      />
      <circle cx="27" cy="13" r="2.2" className="fill-agent" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="leading-none">
        <span className="font-display text-[1.45rem] tracking-tight">Afya</span>{" "}
        <span className="text-sm font-medium text-muted-foreground">Triage Watch</span>
      </span>
    </span>
  );
}
