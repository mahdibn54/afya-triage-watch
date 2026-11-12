/// <reference lib="webworker" />
// E7-16: Whisper speech-to-text in the nurse's browser (transformers.js in a Web Worker). Audio never leaves the
// device: the model files come from Hugging Face once and are cached by the browser; transcription runs here.
import { pipeline, Tensor, type AutomaticSpeechRecognitionPipeline } from "@huggingface/transformers";

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

// The languages spoken at the triage desk. Detection picks among these only, so a short complaint is not
// mistaken for a neighbouring language.
const LANGUAGES = ["en", "fr", "sw"];

/** Whisper's own language detection: one decoder step after <|startoftranscript|>, the most likely language token. */
async function detectLanguage(run: AutomaticSpeechRecognitionPipeline, audio: Float32Array): Promise<string> {
  try {
    const cfg = run.model.generation_config as unknown as { decoder_start_token_id: number; lang_to_id: Record<string, number> };
    const { input_features } = await run.processor(audio.slice(0, 16000 * 30));
    const sot = new Tensor("int64", BigInt64Array.from([BigInt(cfg.decoder_start_token_id)]), [1, 1]);
    const { logits } = (await run.model({ input_features, decoder_input_ids: sot })) as { logits: Tensor };
    const scores = logits.data as Float32Array;
    const vocab = logits.dims[logits.dims.length - 1];
    const last = scores.length - vocab; // logits of the last (only) decoder position
    let best = "en";
    let bestScore = -Infinity;
    for (const code of LANGUAGES) {
      const id = cfg.lang_to_id[`<|${code}|>`];
      if (id !== undefined && scores[last + id] > bestScore) {
        best = code;
        bestScore = scores[last + id];
      }
    }
    return best;
  } catch {
    return "en";
  }
}

addEventListener("message", async (ev: MessageEvent<In>) => {
  const msg = ev.data;
  if (msg.type === "load") {
    load().catch(() => {});
    return;
  }
  try {
    const run = await load();
    // Transcribe, never translate: a Swahili or French complaint stays in its language. transformers.js has no
    // language detection and falls back to English (which translates), so detect it first.
    const language = await detectLanguage(run, msg.audio);
    const out = await run(msg.audio, { task: "transcribe", language, chunk_length_s: 30, stride_length_s: 5 });
    const text = (Array.isArray(out) ? out.map((o) => o.text).join(" ") : out.text).trim();
    postMessage({ type: "result", id: msg.id, text, language });
  } catch (e) {
    postMessage({ type: "failed", id: msg.id, message: String((e as Error)?.message ?? e) });
  }
});
