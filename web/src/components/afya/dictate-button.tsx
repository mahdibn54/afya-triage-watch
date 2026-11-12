"use client";

// E7-16: a microphone button for the free-text fields (complaint, override reason, reject reason). Press to record,
// press again to stop; Whisper transcribes in a Web Worker and the text is appended to the field for the nurse to
// edit. Nothing is saved until the nurse presses the form's own button. Audio is never sent or stored.
import { Loader2, Mic, MicOff, Square } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

type ModelState = "idle" | "loading" | "ready" | "error";

let worker: Worker | null = null;
let modelState: ModelState = "idle";
let nextId = 1;
const listeners = new Set<() => void>();
const pending = new Map<number, { resolve: (t: string) => void; reject: (e: Error) => void }>();

function setModelState(s: ModelState) {
  modelState = s;
  listeners.forEach((l) => l());
}

function getWorker(): Worker {
  if (!worker) {
    worker = new Worker(new URL("./dictation.worker.ts", import.meta.url), { type: "module" });
    worker.addEventListener("error", () => setModelState("error")); // the worker script itself failed to load
    worker.addEventListener("message", (ev: MessageEvent) => {
      const m = ev.data as { type: string; id?: number; text?: string; message?: string };
      if (m.type === "ready") setModelState("ready");
      else if (m.type === "error") setModelState("error");
      else if (m.id !== undefined) {
        const p = pending.get(m.id);
        pending.delete(m.id);
        if (m.type === "result") p?.resolve(m.text ?? "");
        else p?.reject(new Error(m.message ?? "transcription failed"));
      }
    });
  }
  return worker;
}

/** Start downloading the model in the background (call after sign-in). Safe to call more than once. */
export function preloadDictation() {
  if (typeof window === "undefined" || modelState === "loading" || modelState === "ready") return;
  setModelState("loading");
  getWorker().postMessage({ type: "load" });
}

function useModelState(): ModelState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => modelState,
    () => "idle",
  );
}

function transcribe(audio: Float32Array): Promise<string> {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    getWorker().postMessage({ type: "transcribe", id, audio }, [audio.buffer]);
  });
}

/** Decode the recording to 16 kHz mono, the input Whisper expects. */
async function toPcm16k(blob: Blob): Promise<Float32Array> {
  const ctx = new AudioContext({ sampleRate: 16000 });
  try {
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
    if (buf.numberOfChannels === 1) return buf.getChannelData(0).slice();
    const a = buf.getChannelData(0);
    const b = buf.getChannelData(1);
    const mono = new Float32Array(a.length);
    for (let i = 0; i < a.length; i++) mono[i] = (a[i] + b[i]) / 2;
    return mono;
  } finally {
    void ctx.close();
  }
}

type Phase = "idle" | "listening" | "transcribing" | "blocked" | "failed";

export function DictateButton({ onText, label, className }: { onText: (text: string) => void; label: string; className?: string }) {
  const model = useModelState();
  const [phase, setPhase] = useState<Phase>("idle");
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);

  useEffect(() => {
    preloadDictation();
    return () => {
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function start() {
    if (model !== "ready") return;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.current = s;
      const chunks: Blob[] = [];
      const r = new MediaRecorder(s);
      r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      r.onstop = async () => {
        s.getTracks().forEach((t) => t.stop());
        stream.current = null;
        setPhase("transcribing");
        try {
          const text = await transcribe(await toPcm16k(new Blob(chunks, { type: r.mimeType })));
          if (text) onText(text);
          setPhase("idle");
        } catch {
          setPhase("failed");
        }
      };
      rec.current = r;
      r.start();
      setPhase("listening");
    } catch {
      setPhase("blocked");
    }
  }

  function stop() {
    rec.current?.stop();
    rec.current = null;
  }

  const listening = phase === "listening";
  const busy = phase === "transcribing";
  const notReady = model !== "ready";
  const status = listening
    ? "Listening… press again to stop"
    : busy
      ? "Writing it down…"
      : phase === "blocked"
        ? "Microphone blocked: allow it in the browser, or type"
        : phase === "failed"
          ? "Could not transcribe: please type"
          : model === "error"
            ? "Dictation unavailable: please type"
            : notReady
              ? "Dictation loading…"
              : null;

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {status && (
        <span aria-live="polite" className={cn("text-xs", listening ? "font-medium text-destructive" : "text-muted-foreground")}>
          {status}
        </span>
      )}
      <button
        type="button"
        data-testid="dictate"
        aria-label={listening ? `Stop dictating ${label}` : `Dictate ${label}`}
        aria-pressed={listening}
        title={notReady ? "Dictation is loading or unavailable; typing always works" : `Dictate ${label}`}
        disabled={busy || (notReady && !listening)}
        onClick={() => (listening ? stop() : void start())}
        className={cn(
          "grid size-11 shrink-0 place-items-center rounded-full border bg-background text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50",
          listening && "animate-pulse border-destructive bg-destructive text-white hover:text-white",
        )}
      >
        {busy ? (
          <Loader2 className="size-4 animate-spin" />
        ) : listening ? (
          <Square className="size-3.5 fill-current" />
        ) : phase === "blocked" || model === "error" ? (
          <MicOff className="size-4" />
        ) : (
          <Mic className="size-4" />
        )}
      </button>
    </span>
  );
}

/** Append dictated text to what is already in a field, with one space between. */
export function appendText(current: string, add: string, max?: number): string {
  const joined = current.trim() ? `${current.replace(/\s+$/, "")} ${add}` : add;
  return max ? joined.slice(0, max) : joined;
}
