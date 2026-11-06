"use client";

import { Check, Loader2, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import type { Consciousness, Me, Mobility, QueuePatient, RemeasureProblem, VitalsRequest } from "@/api/contract";
import { ColourChip } from "@/components/afya/colour-chip";
import { NoticeCallout } from "@/components/afya/notice-chip";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { ApiError, newIdempotencyKey } from "@/lib/api";
import { useRecordVitals } from "@/lib/queries";
import { INPUT_LABEL } from "@/lib/sats";
import { cn } from "@/lib/utils";

type NumKey = "resp_rate" | "heart_rate" | "systolic_bp" | "temperature" | "spo2";

const NUMBERS: { key: NumKey; unit: string; placeholder: string; step: string; note?: string }[] = [
  { key: "resp_rate", unit: "/min", placeholder: "18", step: "1" },
  { key: "heart_rate", unit: "/min", placeholder: "80", step: "1" },
  { key: "systolic_bp", unit: "mmHg", placeholder: "120", step: "1" },
  { key: "temperature", unit: "°C", placeholder: "37.0", step: "0.1" },
  { key: "spo2", unit: "%", placeholder: "98", step: "1", note: "shown, not scored" },
];

const MOBILITY: [Mobility, string][] = [
  ["walking", "Walking"],
  ["with_help", "With help"],
  ["stretcher", "Stretcher"],
];
const AVPU: [Consciousness, string][] = [
  ["alert", "Alert"],
  ["confused", "Confused"],
  ["voice", "Voice"],
  ["pain", "Pain"],
  ["unresponsive", "Unresp."],
];
const TRAUMA: ["yes" | "no", string][] = [
  ["no", "No"],
  ["yes", "Yes"],
];

/** P-014's next reading in docs/api.md (demo only: lets the presenter fill the form in one tap). */
const SCENARIO: Form = {
  resp_rate: "26",
  heart_rate: "112",
  systolic_bp: "120",
  temperature: "38.6",
  spo2: "93",
  mobility: "walking",
  consciousness: "alert",
  trauma: "no",
  complaint: "Short of breath since morning. My mother had chest pain last year.",
};

type Form = Record<NumKey, string> & {
  mobility: Mobility | "";
  consciousness: Consciousness | "";
  trauma: "yes" | "no" | "";
  complaint: string;
};

const EMPTY: Form = {
  resp_rate: "",
  heart_rate: "",
  systolic_bp: "",
  temperature: "",
  spo2: "",
  mobility: "",
  consciousness: "",
  trauma: "",
  complaint: "",
};

const MAX_COMPLAINT = 500;
export const DEMO_LABEL = "P-014";

export function VitalsDialog({ me, patient, onClose }: { me: Me; patient: QueuePatient | null; onClose: () => void }) {
  return (
    <Dialog open={!!patient} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[94dvh] overflow-x-hidden overflow-y-auto p-0 sm:max-w-2xl" showCloseButton>
        {patient && <VitalsForm key={patient.visit_id} me={me} patient={patient} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function VitalsForm({ me, patient, onClose }: { me: Me; patient: QueuePatient; onClose: () => void }) {
  const [form, setForm] = useState<Form>(EMPTY);
  // One key per attempt to save this reading: a retry after a network error reuses it, so it is never saved twice.
  const [key, setKey] = useState(() => newIdempotencyKey());
  const [remeasure, setRemeasure] = useState<RemeasureProblem[]>([]);
  const [invalid, setInvalid] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<{ observation_id: string } | null>(null);
  const save = useRecordVitals();

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    setRemeasure((r) => r.filter((p) => p.name !== k));
    setInvalid((i) => {
      const { [k]: _, ...rest } = i;
      void _;
      return rest;
    });
  };

  const complaintLen = Array.from(form.complaint).length;
  const filled = useMemo(
    () => NUMBERS.some((n) => form[n.key].trim() !== "") || !!form.mobility || !!form.consciousness || !!form.trauma,
    [form],
  );

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const local: Record<string, string> = {};
    const body: VitalsRequest = { visit_id: patient.visit_id, idempotency_key: key };
    for (const n of NUMBERS) {
      const raw = form[n.key].trim().replace(",", ".");
      if (!raw) continue;
      const v = Number(raw);
      if (!Number.isFinite(v)) local[n.key] = "Enter a number";
      else body[n.key] = v;
    }
    if (form.mobility) body.mobility = form.mobility;
    if (form.consciousness) body.consciousness = form.consciousness;
    if (form.trauma) body.trauma = form.trauma;
    if (form.complaint.trim()) body.complaint = form.complaint.trim();
    if (complaintLen > MAX_COMPLAINT) local.complaint = `At most ${MAX_COMPLAINT} characters`;
    if (Object.keys(local).length) {
      setInvalid(local);
      return;
    }
    save.mutate(body, {
      onSuccess: (res) => {
        if (res.status === "remeasure") {
          setRemeasure(res.problems);
          setKey(newIdempotencyKey());
          return;
        }
        setSaved({ observation_id: res.observation_id });
      },
      onError: (err) => {
        if (err instanceof ApiError && err.code === "invalid" && Array.isArray(err.problems)) {
          const map: Record<string, string> = {};
          // The real API names the input in `field` (api/afya_api/errors.py); older fixtures used `name`.
          for (const p of err.problems as { field?: string; name?: string; message: string }[]) {
            const k = p.field ?? p.name;
            if (k) map[k] = p.message;
          }
          if (Object.keys(map).length === 0) map._form = err.message;
          setInvalid(map);
          setKey(newIdempotencyKey());
        }
      },
    });
  }

  if (saved) {
    return (
      <div className="flex flex-col items-center px-8 py-12 text-center" data-testid="vitals-saved">
        <span className="grid size-16 place-items-center rounded-full bg-ok-soft text-ok">
          <svg viewBox="0 0 24 24" className="size-9 animate-tick" aria-hidden>
            <path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="animate-draw" />
          </svg>
        </span>
        <DialogTitle className="mt-5 font-display text-3xl font-normal">Reading saved</DialogTitle>
        <DialogDescription className="mt-2 max-w-sm text-base">
          {patient.patient_label}&apos;s new reading is in the record as{" "}
          <span className="font-mono text-foreground">{saved.observation_id}</span>. The watch agent re-scores it now and
          will ask you for a second look if the patient is worse.
        </DialogDescription>
        <p className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-agent-soft px-3 py-1 text-xs font-medium text-agent-foreground">
          <Sparkles className="size-3.5" /> Nothing changes on the board until a nurse confirms
        </p>
        <button
          type="button"
          autoFocus
          onClick={onClose}
          className="mt-8 h-12 rounded-xl bg-primary px-8 text-base font-semibold text-primary-foreground hover:bg-primary/90"
        >
          Back to the waiting room
        </button>
      </div>
    );
  }

  const bad = new Set([...remeasure.map((p) => p.name as string), ...Object.keys(invalid)]);

  return (
    <form onSubmit={submit} noValidate>
      <div className="border-b px-6 pt-6 pb-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pr-8">
          <DialogTitle className="font-display text-2xl font-normal whitespace-nowrap sm:text-3xl">Record vitals</DialogTitle>
          <span className="font-mono text-lg font-semibold whitespace-nowrap">{patient.patient_label}</span>
          <ColourChip colour={patient.confirmed_colour} size="sm" />
        </div>
        <DialogDescription className="mt-1">
          Leave a field empty if you did not measure it: missing values are reported, never guessed.
        </DialogDescription>
        {me.demo && patient.patient_label === DEMO_LABEL && (
          <button
            type="button"
            data-testid="fill-scenario"
            onClick={() => {
              setForm(SCENARIO);
              setRemeasure([]);
              setInvalid({});
            }}
            className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-lg border border-dashed border-warn/70 bg-warn-soft px-2.5 text-xs font-medium"
          >
            Demo: fill P-014&apos;s next reading
          </button>
        )}
      </div>

      <div className="space-y-6 px-6 py-5">
        {remeasure.length > 0 && (
          <NoticeCallout code="remeasure" className="animate-rise">
            <ul className="mt-2 space-y-0.5">
              {remeasure.map((p) => (
                <li key={p.name} className="tnum font-medium">
                  {INPUT_LABEL[p.name]}: {p.value} is outside {p.min} to {p.max}.
                </li>
              ))}
            </ul>
          </NoticeCallout>
        )}

        <fieldset>
          <legend className="mb-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Measurements</legend>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {NUMBERS.map((n) => (
              <label key={n.key} className="block">
                <span className="flex items-baseline justify-between text-sm font-medium">
                  {INPUT_LABEL[n.key]}
                  {n.note && <span className="text-[11px] font-normal text-muted-foreground">{n.note}</span>}
                </span>
                <span
                  className={cn(
                    "mt-1 flex h-12 items-center rounded-xl border bg-background pr-3 focus-within:ring-3 focus-within:ring-ring/30",
                    bad.has(n.key) && "border-destructive ring-3 ring-destructive/15",
                  )}
                >
                  <input
                    name={n.key}
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder={n.placeholder}
                    value={form[n.key]}
                    onChange={(e) => set(n.key, e.target.value)}
                    aria-invalid={bad.has(n.key) || undefined}
                    className="tnum h-full w-full min-w-0 bg-transparent px-3 text-lg font-semibold outline-none placeholder:font-normal placeholder:text-muted-foreground/50"
                  />
                  <span className="text-sm text-muted-foreground">{n.unit}</span>
                </span>
                {invalid[n.key] && <span className="mt-1 block text-xs text-destructive">{invalid[n.key]}</span>}
              </label>
            ))}
          </div>
        </fieldset>

        <Segmented label="Mobility" name="mobility" options={MOBILITY} value={form.mobility} onChange={(v) => set("mobility", v)} error={invalid.mobility} />
        <Segmented
          label="Consciousness (AVPU)"
          name="consciousness"
          options={AVPU}
          value={form.consciousness}
          onChange={(v) => set("consciousness", v)}
          error={invalid.consciousness}
        />
        <Segmented label="Trauma" name="trauma" options={TRAUMA} value={form.trauma} onChange={(v) => set("trauma", v)} error={invalid.trauma} />

        <label className="block">
          <span className="flex items-baseline justify-between text-sm font-medium">
            Complaint, in the patient&apos;s own words
            <span className={cn("tnum text-xs font-normal text-muted-foreground", complaintLen > MAX_COMPLAINT && "text-destructive")}>
              {complaintLen} / {MAX_COMPLAINT}
            </span>
          </span>
          <textarea
            name="complaint"
            rows={3}
            value={form.complaint}
            onChange={(e) => set("complaint", e.target.value)}
            placeholder="e.g. Short of breath since morning."
            className={cn(
              "mt-1 block w-full resize-y rounded-xl border bg-background px-3 py-2.5 text-base outline-none focus:ring-3 focus:ring-ring/30",
              bad.has("complaint") && "border-destructive",
            )}
          />
          <span className="mt-1 block text-xs text-muted-foreground">
            Optional. Any language. Only used to match SATS signs; it is shown back to you as plain text.
          </span>
          {invalid.complaint && <span className="mt-1 block text-xs text-destructive">{invalid.complaint}</span>}
        </label>

        {save.isError && !(save.error instanceof ApiError && save.error.code === "invalid") && (
          <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {save.error instanceof ApiError && save.error.status === 403
              ? "Only a nurse or clinician can record vitals."
              : `Not saved: ${save.error.message} You can safely try again; the reading will not be saved twice.`}
          </p>
        )}
        {Object.keys(invalid).length > 0 && (
          <p role="alert" className="text-sm text-destructive">
            {invalid._form ?? "Check the highlighted values."}
          </p>
        )}
      </div>

      <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t bg-popover/95 px-6 py-4 backdrop-blur">
        <p className="hidden text-xs text-muted-foreground sm:block">Recorded by {me.name}</p>
        <div className="flex flex-1 justify-end gap-2">
          <button type="button" onClick={onClose} className="h-12 rounded-xl border px-4 whitespace-nowrap sm:px-5 text-sm font-medium hover:bg-muted">
            Cancel
          </button>
          <button
            type="submit"
            data-testid="save-vitals"
            disabled={!filled || save.isPending}
            className="inline-flex h-12 items-center gap-2 rounded-xl bg-primary px-5 text-sm whitespace-nowrap sm:px-6 font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
          >
            {save.isPending ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
            Save reading
          </button>
        </div>
      </div>
    </form>
  );
}

function Segmented<T extends string>({
  label,
  name,
  options,
  value,
  onChange,
  error,
}: {
  label: string;
  name: string;
  options: [T, string][];
  value: T | "";
  onChange: (v: T | "") => void;
  error?: string;
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium">{label}</legend>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
        {options.map(([v, text]) => {
          const on = value === v;
          return (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={on}
              data-name={name}
              data-value={v}
              onClick={() => onChange(on ? "" : v)}
              className={cn(
                "h-11 min-w-[4.5rem] rounded-xl border px-3.5 text-sm font-medium transition",
                on ? "border-primary bg-primary text-primary-foreground shadow-sm" : "bg-background hover:bg-muted",
              )}
            >
              {text}
            </button>
          );
        })}
      </div>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </fieldset>
  );
}
