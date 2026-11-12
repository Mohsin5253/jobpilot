// Run: node --experimental-strip-types --test lib/flow/flow.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { resample } from "./capture.ts";
import { editRatio } from "./edit.ts";
import { normalise, trim } from "./vad.ts";
import { encodeWav } from "./wav.ts";

const RATE = 16000;
const tone = (ms: number, amp: number) => Float32Array.from({ length: (RATE * ms) / 1000 }, (_, i) => amp * Math.sin((2 * Math.PI * 220 * i) / RATE));
const noise = (ms: number, amp: number) => Float32Array.from({ length: (RATE * ms) / 1000 }, () => amp * (Math.random() * 2 - 1));
const cat = (...xs: Float32Array[]) => {
  const out = new Float32Array(xs.reduce((n, x) => n + x.length, 0));
  let o = 0;
  for (const x of xs) out.set(x, o), (o += x.length);
  return out;
};

test("VAD trims silence around speech and pads it", () => {
  const take = cat(noise(800, 0.002), tone(1200, 0.3), noise(900, 0.002));
  const r = trim(take, RATE);
  assert.ok(r.speech);
  const ms = (r.audio.length / RATE) * 1000;
  assert.ok(ms > 1200 && ms < 1600, `kept ${ms} ms`); // speech plus ~150 ms padding each side
});

test("VAD sends nothing for silence or a click", () => {
  assert.equal(trim(noise(2000, 0.002), RATE).speech, false);
  assert.equal(trim(cat(noise(1000, 0.002), tone(90, 0.5), noise(1000, 0.002)), RATE).speech, false);
});

test("quiet speech is detected and boosted (whisper mode)", () => {
  const r = trim(cat(noise(500, 0.0005), tone(1000, 0.01), noise(500, 0.0005)), RATE);
  assert.ok(r.speech && r.quiet);
  assert.ok(Math.max(...r.audio) > 0.3);
});

test("peak normalised to about -3 dBFS", () => {
  const out = normalise(tone(200, 0.1));
  const peak = Math.max(...out.map(Math.abs));
  assert.ok(Math.abs(peak - 0.708) < 0.01, String(peak));
});

test("WAV header and size", async () => {
  const blob = encodeWav(tone(1000, 0.5), RATE);
  const buf = new DataView(await blob.arrayBuffer());
  assert.equal(blob.size, 44 + RATE * 2);
  assert.equal(String.fromCharCode(buf.getUint8(0), buf.getUint8(1), buf.getUint8(2), buf.getUint8(3)), "RIFF");
  assert.equal(buf.getUint32(24, true), RATE);
});

test("resample 48 kHz to 16 kHz", () => {
  assert.equal(resample(new Float32Array(48000), 48000, 16000).length, 16000);
});

test("edit ratio: untouched, edited, extended", () => {
  const d = "I built a Flask API for 200 students";
  assert.equal(editRatio(d, d), 0);
  assert.equal(editRatio(d, `${d}. I also wrote the tests.`), 0); // typing more after isn't editing the take
  assert.ok(editRatio(d, "I built a FastAPI service for 200 students") > 0.2);
});
