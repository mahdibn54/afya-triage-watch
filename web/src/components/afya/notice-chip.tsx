"use client";

import { AlertTriangle, BellRing, DatabaseZap, FileQuestion, Info, MessageSquareWarning, PencilRuler, Ruler, Sparkles, WifiOff } from "lucide-react";

import type { Notice, NoticeCode } from "@/api/contract";
import { noticeText } from "@/lib/notices";
import { cn } from "@/lib/utils";

const ICON: Record<NoticeCode, React.ComponentType<{ className?: string }>> = {
  remeasure: Ruler,
  no_chart: PencilRuler,
  not_reviewed: Sparkles,
  instruction_like_text: MessageSquareWarning,
  vitals_due: AlertTriangle,
  clinician_reminded: BellRing,
  model_unavailable: WifiOff,
  fhir_unavailable: DatabaseZap,
  data_incomplete: FileQuestion,
};

export const TONE = {
  warn: "bg-warn-soft text-[color-mix(in_oklch,var(--warn),black_35%)] dark:text-warn border-warn/30",
  agent: "bg-agent-soft text-agent-foreground border-agent/25",
  info: "bg-muted text-foreground border-border",
  muted: "bg-muted text-muted-foreground border-border",
} as const;

export function NoticeChip({ notice, className }: { notice: Notice; className?: string }) {
  const n = noticeText(notice.code);
  const Icon = ICON[notice.code] ?? Info;
  return (
    <span
      title={n.title}
      className={cn("inline-flex h-6 items-center gap-1 rounded-full border px-2 text-[11px] font-medium", TONE[n.tone], className)}
    >
      <Icon className="size-3.5" />
      {n.short}
    </span>
  );
}

export function NoticeCallout({
  code,
  className,
  action,
  children,
}: {
  code: NoticeCode;
  className?: string;
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const n = noticeText(code);
  const Icon = ICON[code] ?? Info;
  return (
    <div role="status" className={cn("flex items-start gap-3 rounded-xl border p-3 text-sm", TONE[n.tone], className)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{n.title}</p>
        <p className="mt-0.5 opacity-90">{n.body}</p>
        {children}
      </div>
      {action}
    </div>
  );
}
