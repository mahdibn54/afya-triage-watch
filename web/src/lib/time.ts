"use client";

import { useEffect, useState } from "react";

/** Server clock = client clock + skew, learnt from the queue's `as_of`. Countdowns use it. */
let skewMs = 0;
export function learnServerTime(asOf: string, receivedAt: number): void {
  const s = Date.parse(asOf);
  if (!Number.isNaN(s)) skewMs = s - receivedAt;
}
export function serverNow(): number {
  return Date.now() + skewMs;
}

/** Re-renders every `ms` with the current server time. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => serverNow());
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
export function clockShort(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function mmss(totalSeconds: number): string {
  const s = Math.max(0, Math.round(Math.abs(totalSeconds)));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h} h ${String(m).padStart(2, "0")} min`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function ago(fromMs: number, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - fromMs) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.floor(m / 60)} h ${m % 60} min ago`;
}

/** Client clock, re-rendering every `ms` (for "updated n s ago", which compares client timestamps). */
export function useClientNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
