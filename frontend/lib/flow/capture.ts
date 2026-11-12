/**
 * Microphone capture for push-to-talk dictation.
 * - 16 kHz mono float32 (resampled if the device can't open at 16 kHz).
 * - A pre-roll ring buffer keeps the last 500 ms at all times, so a first syllable spoken a moment before the key
 *   isn't clipped; a 250 ms post-roll keeps recording after release, because people release mid-word.
 * The mic stays open while the answer box is active (like a call), and is released when it isn't.
 */
export const TARGET_RATE = 16000;
const PRE_ROLL_MS = 500;
const POST_ROLL_MS = 250;

export class Capture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: ScriptProcessorNode | null = null;
  private ring: Float32Array = new Float32Array(0);
  private ringPos = 0;
  private ringFull = false;
  private chunks: Float32Array[] = [];
  private recording = false;
  rate = TARGET_RATE;
  level = 0; // 0..1, for the meter
  onLevel?: (v: number) => void;

  get open() {
    return !!this.ctx;
  }

  async openMic(): Promise<void> {
    if (this.ctx) return;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: true } });
    let ctx: AudioContext;
    try {
      ctx = new AudioContext({ sampleRate: TARGET_RATE });
    } catch {
      ctx = new AudioContext(); // some browsers can't open at 16 kHz; we resample on the way out
    }
    this.ctx = ctx;
    this.rate = ctx.sampleRate;
    this.ring = new Float32Array(Math.ceil((this.rate * PRE_ROLL_MS) / 1000));
    const src = ctx.createMediaStreamSource(this.stream);
    // ScriptProcessor is deprecated but runs everywhere without a separate worklet file (which our CSP would block).
    const node = ctx.createScriptProcessor(2048, 1, 1);
    node.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      let peak = 0;
      for (let i = 0; i < input.length; i++) peak = Math.max(peak, Math.abs(input[i]));
      this.level = Math.min(1, peak * 2.5);
      this.onLevel?.(this.level);
      if (this.recording) {
        this.chunks.push(new Float32Array(input));
      } else {
        for (let i = 0; i < input.length; i++) {
          this.ring[this.ringPos] = input[i];
          this.ringPos = (this.ringPos + 1) % this.ring.length;
          if (this.ringPos === 0) this.ringFull = true;
        }
      }
    };
    src.connect(node);
    node.connect(ctx.destination); // required for onaudioprocess to fire; the node outputs silence
    this.node = node;
  }

  /** Start keeping audio, beginning with the pre-roll already buffered. */
  begin(): void {
    const pre = this.ringFull ? new Float32Array([...this.ring.subarray(this.ringPos), ...this.ring.subarray(0, this.ringPos)]) : this.ring.slice(0, this.ringPos);
    this.chunks = [pre];
    this.recording = true;
  }

  /** Stop after the post-roll and return the take at 16 kHz. */
  async end(): Promise<Float32Array> {
    await new Promise((r) => setTimeout(r, POST_ROLL_MS));
    this.recording = false;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const out = new Float32Array(total);
    let o = 0;
    for (const c of this.chunks) {
      out.set(c, o);
      o += c.length;
    }
    this.chunks = [];
    this.ringPos = 0;
    this.ringFull = false;
    return this.rate === TARGET_RATE ? out : resample(out, this.rate, TARGET_RATE);
  }

  close(): void {
    this.recording = false;
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.stream = null;
    this.node = null;
  }
}

/** Linear-interpolation resampler (good enough for speech going to an ASR model). */
export function resample(x: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return x;
  const n = Math.floor((x.length * to) / from);
  const out = new Float32Array(n);
  const step = from / to;
  for (let i = 0; i < n; i++) {
    const pos = i * step;
    const j = Math.floor(pos);
    const f = pos - j;
    out[i] = (x[j] ?? 0) * (1 - f) + (x[j + 1] ?? x[j] ?? 0) * f;
  }
  return out;
}
