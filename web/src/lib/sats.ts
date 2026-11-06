import type { Colour } from "@/api/contract";

// SATS colours are never shown by colour alone: each has a label and a shape (docs/web-design.md).
export const SATS: Record<
  Colour,
  { label: string; shape: string; rank: number; target: number; bg: string; soft: string; ink: string; text: string; ring: string }
> = {
  RED: {
    label: "Red", shape: "■", rank: 4, target: 0,
    bg: "bg-sats-red", soft: "bg-sats-red-soft", ink: "text-sats-red-ink", text: "text-white", ring: "ring-sats-red",
  },
  ORANGE: {
    label: "Orange", shape: "▲", rank: 3, target: 10,
    bg: "bg-sats-orange", soft: "bg-sats-orange-soft", ink: "text-sats-orange-ink", text: "text-white", ring: "ring-sats-orange",
  },
  YELLOW: {
    label: "Yellow", shape: "●", rank: 2, target: 60,
    bg: "bg-sats-yellow", soft: "bg-sats-yellow-soft", ink: "text-sats-yellow-ink", text: "text-[oklch(0.3_0.06_85)]", ring: "ring-sats-yellow",
  },
  GREEN: {
    label: "Green", shape: "○", rank: 1, target: 240,
    bg: "bg-sats-green", soft: "bg-sats-green-soft", ink: "text-sats-green-ink", text: "text-white", ring: "ring-sats-green",
  },
};

export const COLOURS: Colour[] = ["RED", "ORANGE", "YELLOW", "GREEN"];

export const INPUT_LABEL: Record<string, string> = {
  resp_rate: "Respiratory rate",
  heart_rate: "Heart rate",
  systolic_bp: "Systolic BP",
  temperature: "Temperature",
  spo2: "SpO₂",
  mobility: "Mobility",
  consciousness: "Consciousness (AVPU)",
  trauma: "Trauma",
};

export const INPUT_SHORT: Record<string, string> = {
  resp_rate: "RR",
  heart_rate: "HR",
  systolic_bp: "SBP",
  temperature: "Temp",
  spo2: "SpO₂",
  mobility: "Mobility",
  consciousness: "AVPU",
  trauma: "Trauma",
};

/** UCUM codes from the API → what a nurse reads. */
export function unitLabel(unit: string | null | undefined): string {
  if (!unit) return "";
  return ({ "/min": "/min", "Cel": "°C", "mm[Hg]": "mmHg", "%": "%" } as Record<string, string>)[unit] ?? unit;
}

export const VALUE_LABEL: Record<string, string> = {
  walking: "Walking",
  with_help: "With help",
  stretcher: "Stretcher / immobile",
  alert: "Alert",
  confused: "Confused",
  voice: "Responds to voice",
  pain: "Responds to pain",
  unresponsive: "Unresponsive",
  yes: "Yes",
  no: "No",
};

export function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "–";
  return typeof v === "number" ? String(v) : (VALUE_LABEL[String(v)] ?? String(v));
}
