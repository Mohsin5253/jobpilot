/**
 * Push-to-talk keys: hold Right Ctrl (or Right Option/Alt on a Mac keyboard, which has no Right Ctrl) to talk;
 * double-tap to switch to hands-free, and press again to stop. Key repeat is ignored.
 */
export const PTT_CODES = new Set(["ControlRight", "AltRight"]);
const TAP_MS = 250;
const DOUBLE_TAP_MS = 400;

export type HotkeyHandlers = { onDown: () => void; onUp: () => void; onDoubleTap: () => void; isHandsFree: () => boolean };

export function bindPushToTalk(h: HotkeyHandlers): () => void {
  let downAt = 0;
  let lastTapUp = 0;
  let held = false;
  const down = (e: KeyboardEvent) => {
    if (!PTT_CODES.has(e.code) || e.repeat) return;
    e.preventDefault();
    held = true;
    downAt = performance.now();
    if (h.isHandsFree()) return; // the release ends hands-free (below)
    h.onDown();
  };
  const up = (e: KeyboardEvent) => {
    if (!PTT_CODES.has(e.code) || !held) return;
    e.preventDefault();
    held = false;
    const now = performance.now();
    if (h.isHandsFree()) {
      h.onUp();
      return;
    }
    const tap = now - downAt < TAP_MS;
    h.onUp();
    if (tap && now - lastTapUp < DOUBLE_TAP_MS) {
      lastTapUp = 0;
      h.onDoubleTap();
    } else if (tap) {
      lastTapUp = now;
    }
  };
  window.addEventListener("keydown", down);
  window.addEventListener("keyup", up);
  return () => {
    window.removeEventListener("keydown", down);
    window.removeEventListener("keyup", up);
  };
}
