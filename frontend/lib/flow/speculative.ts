/**
 * Flowtype's speculative chunking, in the browser: while you're still talking, a finished stretch of a long answer
 * is sent off to be transcribed. At a natural pause (at least 500 ms of silence) after at least 4 s of audio, the
 * audio up to the middle of that pause becomes a chunk. When you let go only the rest is left to transcribe, so a
 * 90-second answer appears about as fast as a 5-second one (measured on the desktop app: 250 ms after release for a
 * 25 s dictation, against 492 ms as one request).
 */
const FRAME_MS = 30;

export type CutOptions = { minChunkMs?: number; pauseMs?: number; tailMs?: number };

/** The sample index to cut at (the middle of the last long-enough pause), or null when there's no good place yet. */
export function findCut(x: Float32Array, rate: number, { minChunkMs = 4000, pauseMs = 500, tailMs = 300 }: CutOptions = {}): number | null {
  const frame = Math.round((rate * FRAME_MS) / 1000);
  const usable = x.length - Math.round((rate * tailMs) / 1000); // the newest audio may be a word still being said
  const n = Math.floor(usable / frame);
  const minFrames = Math.ceil(minChunkMs / FRAME_MS);
  const pauseFrames = Math.ceil(pauseMs / FRAME_MS);
  if (n < minFrames + pauseFrames) return null;
  const e = new Array<number>(n);
  for (let f = 0; f < n; f++) {
    let s = 0;
    for (let i = f * frame; i < (f + 1) * frame; i++) s += x[i] * x[i];
    e[f] = 20 * Math.log10(Math.max(Math.sqrt(s / frame), 1e-9));
  }
  const sorted = [...e].sort((a, b) => a - b);
  const floor = sorted[Math.floor(sorted.length * 0.05)]; // the quietest frames: long answers are mostly speech
  const loudest = sorted[sorted.length - 1];
  if (loudest - floor < 12) return null; // no clear speech in it (or no clear silence)
  const threshold = Math.max(floor + 9, -50);
  let lastSpeech = -1;
  let best: number | null = null;
  let run = 0;
  for (let f = 0; f < n; f++) {
    if (e[f] > threshold) {
      // A pause long enough, after enough audio, with speech on both sides: cut in its middle.
      if (run >= pauseFrames && lastSpeech >= 0 && f - run >= minFrames) best = (f - Math.floor(run / 2)) * frame;
      lastSpeech = f;
      run = 0;
    } else {
      run++;
    }
  }
  return best;
}
