/**
 * Voice activity detection on a finished take: trims leading and trailing silence, and says "no speech" so nothing
 * is sent (which is what stops Whisper's silence hallucinations: "Thank you for watching", "Subtitles by…").
 * Energy-based with an adaptive noise floor (the quietest frames of this take). Also normalises the peak to about
 * -3 dBFS and gives quiet speech extra gain ("whisper mode").
 */
const FRAME_MS = 30;
const PAD_MS = 150;
const MIN_SPEECH_MS = 240;

export type VadResult = { audio: Float32Array; speech: boolean; speechMs: number; quiet: boolean };

const db = (rms: number) => 20 * Math.log10(Math.max(rms, 1e-9));

export function trim(x: Float32Array, rate: number): VadResult {
  const frame = Math.round((rate * FRAME_MS) / 1000);
  const n = Math.floor(x.length / frame);
  if (n === 0) return { audio: x, speech: false, speechMs: 0, quiet: true };
  const energies: number[] = [];
  for (let f = 0; f < n; f++) {
    let s = 0;
    for (let i = f * frame; i < (f + 1) * frame; i++) s += x[i] * x[i];
    energies.push(db(Math.sqrt(s / frame)));
  }
  const sorted = [...energies].sort((a, b) => a - b);
  const floor = sorted[Math.floor(sorted.length * 0.2)];
  const loudest = sorted[sorted.length - 1];
  const quiet = loudest < -35; // whisper mode: a lower bar above the floor
  const threshold = Math.max(floor + (quiet ? 6 : 9), quiet ? -60 : -50);
  const speechFrames = energies.map((e) => e > threshold);
  const count = speechFrames.filter(Boolean).length;
  const speechMs = count * FRAME_MS;
  if (speechMs < MIN_SPEECH_MS) return { audio: new Float32Array(0), speech: false, speechMs, quiet };
  const first = speechFrames.indexOf(true);
  const last = speechFrames.lastIndexOf(true);
  const pad = Math.round(PAD_MS / FRAME_MS);
  const a = Math.max(0, first - pad) * frame;
  const b = Math.min(n, last + 1 + pad) * frame;
  return { audio: normalise(x.slice(a, b), quiet), speech: true, speechMs, quiet };
}

/** Peak to about -3 dBFS; quiet takes get up to 4x more gain. */
export function normalise(x: Float32Array, quiet = false): Float32Array {
  let peak = 0;
  for (let i = 0; i < x.length; i++) peak = Math.max(peak, Math.abs(x[i]));
  if (peak < 1e-4) return x;
  const gain = Math.min(0.708 / peak, quiet ? 40 : 10);
  const out = new Float32Array(x.length);
  for (let i = 0; i < x.length; i++) out[i] = Math.max(-1, Math.min(1, x[i] * gain));
  return out;
}
