/** Kept apart from the engine so checking support doesn't download Three.js. */

let supported: boolean | null = null;

/** WebGL available, and the visitor hasn't asked to save data. Otherwise the still images stay. */
export function crew3DSupported(): boolean {
  if (supported !== null) return supported;
  if (typeof window === "undefined") return false;
  const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData;
  try {
    const probe = document.createElement("canvas");
    const gl = probe.getContext("webgl2") || probe.getContext("webgl");
    supported = !saveData && !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext(); // the probe shouldn't hold one of the page's contexts
  } catch {
    supported = false;
  }
  return supported;
}
