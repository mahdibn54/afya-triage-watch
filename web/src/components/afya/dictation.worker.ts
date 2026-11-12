/// <reference lib="webworker" />
// E7-16: Whisper speech-to-text in the nurse's browser (transformers.js in a Web Worker). Audio never leaves the
// device: the model files come from Hugging Face once and are cached by the browser; transcription runs here.
import { pipeline, type AutomaticSpeechRecognitionPipeline } from "@huggingface/transformers";

const MODEL = "onnx-community/whisper-base"; // multilingual; weak on Swahili (known limit, the nurse reads the text)

type In = { type: "load" } | { type: "transcribe"; id: number; audio: Float32Array };

let asr: Promise<AutomaticSpeechRecognitionPipeline> | null = null;

/** WebGPU only when the browser really gives an adapter (many machines list navigator.gpu but have none). */
async function pickDevice(): Promise<"webgpu" | "wasm"> {
  try {
    const gpu = (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
    return gpu && (await gpu.requestAdapter()) ? "webgpu" : "wasm";
  } catch {
    return "wasm";
  }
}

function load(): Promise<AutomaticSpeechRecognitionPipeline> {
  if (!asr) {
    asr = pickDevice().then(
      (device) =>
        pipeline("automatic-speech-recognition", MODEL, {
          device,
          dtype: device === "webgpu" ? "fp32" : "q8",
        }) as Promise<AutomaticSpeechRecognitionPipeline>,
    );
    asr.then(
      () => postMessage({ type: "ready" }),
      (e) => {
        asr = null;
        postMessage({ type: "error", message: String(e?.message ?? e) });
      },
    );
  }
  return asr;
}

addEventListener("message", async (ev: MessageEvent<In>) => {
  const msg = ev.data;
  if (msg.type === "load") {
    load().catch(() => {});
    return;
  }
  try {
    const run = await load();
    // Language auto-detected; transcribe, never translate (a Swahili or French complaint stays in its language).
    const out = await run(msg.audio, { task: "transcribe", chunk_length_s: 30, stride_length_s: 5 });
    const text = (Array.isArray(out) ? out.map((o) => o.text).join(" ") : out.text).trim();
    postMessage({ type: "result", id: msg.id, text });
  } catch (e) {
    postMessage({ type: "failed", id: msg.id, message: String((e as Error)?.message ?? e) });
  }
});
