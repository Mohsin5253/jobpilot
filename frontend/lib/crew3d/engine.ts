/**
 * The 3D crew engine for portraits (every AgentAvatar of 56px and up). Each character is its photoreal
 * render displaced by its depth map into a relief mesh (see material.ts). The head turns toward the
 * pointer while the body barely moves; without a mouse the character glances around on its own.
 * Run status is played by GSAP: working pose, float and light sweep while running, a nod when done,
 * an amber pulse on your turn, stillness and desaturation on error.
 *
 * One WebGL context serves every portrait on the page: each frame it renders a character into a corner
 * of the shared canvas and copies it to that character's own 2D canvas. Only characters on screen render
 * or even download their textures, nothing renders in a hidden tab, and with reduced motion each one
 * renders once per change.
 */

import gsap from "gsap";
import * as THREE from "three";

import { ambientLoop, applyMotion, createCrewMaterial, glanceLoop, loadCrewTextures, newMotion, playStatus, reducedMotion, type Crew3DSource, type Crew3DStatus, type Motion, type StatusPlayer } from "@/lib/crew3d/material";

export type { Crew3DSource, Crew3DStatus } from "@/lib/crew3d/material";

interface Instance extends StatusPlayer {
  /** Starts the texture download; called once, when the character first comes near the screen. */
  load: (() => void) | null;
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
  m: Motion;
  ambient: gsap.core.Timeline;
  glance: gsap.core.Tween;
  look: { x: gsap.QuickToFunc; y: gsap.QuickToFunc };
  visible: boolean;
  ready: boolean;
  dirty: boolean;
  width: number;
  height: number;
  onReady?: () => void;
  resize: ResizeObserver;
}

/** How far a head turns toward the pointer, and how much of that the body follows. */
const MAX_YAW = 0.42;
const MAX_PITCH = 0.2;
const BODY_SHARE = 0.18;

let renderer: THREE.WebGLRenderer | null = null;
const instances = new Set<Instance>();
const pointer = { x: 0, y: 0, active: false };
let ticking = false;

function getRenderer(): THREE.WebGLRenderer {
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, premultipliedAlpha: true, powerPreference: "low-power" });
    renderer.setPixelRatio(1);
    renderer.setClearColor(0x000000, 0);
    renderer.autoClear = false;
    renderer.domElement.addEventListener("webglcontextlost", (e) => e.preventDefault());
  }
  return renderer;
}

function onPointer(e: PointerEvent) {
  if (e.pointerType !== "mouse") return;
  pointer.x = e.clientX;
  pointer.y = e.clientY;
  if (!pointer.active) {
    pointer.active = true;
    instances.forEach((i) => i.glance.pause());
  }
}

function ensureTicker() {
  if (ticking) return;
  ticking = true;
  window.addEventListener("pointermove", onPointer, { passive: true });
  gsap.ticker.add(tick);
}

function stopTickerIfIdle() {
  if (instances.size || !ticking) return;
  ticking = false;
  window.removeEventListener("pointermove", onPointer);
  gsap.ticker.remove(tick);
}

let frame = 0;
const coarse = () => typeof matchMedia !== "undefined" && matchMedia("(pointer: coarse)").matches;

/** Every frame: aim each visible character's head at the pointer, then draw the ones that moved. */
function tick() {
  if (document.hidden || !renderer) return;
  // Phones and tablets draw at 30fps: plenty for breathing and glances, and kinder to the battery.
  if (coarse() && frame++ % 2) return;
  const still = reducedMotion();
  for (const inst of instances) {
    if (inst.load && onScreen(inst)) {
      const load = inst.load;
      inst.load = null;
      load();
    }
    if (!inst.ready) continue;
    inst.visible = onScreen(inst);
    if (!inst.visible) continue;
    if (!still && pointer.active && inst.status !== "error" && inst.status !== "off") {
      const r = inst.canvas.getBoundingClientRect();
      // Aim from the head (upper third of the portrait), not the middle of the frame.
      const nx = gsap.utils.clamp(-1, 1, (pointer.x - (r.left + r.width / 2)) / Math.max(innerWidth * 0.45, 1));
      const ny = gsap.utils.clamp(-1, 1, (pointer.y - (r.top + r.height * 0.32)) / Math.max(innerHeight * 0.55, 1));
      inst.look.x(nx * MAX_YAW);
      inst.look.y(ny * MAX_PITCH);
    }
    if (!still || inst.dirty) draw(inst);
  }
}

/** Match the canvas backing store to its CSS size (capped at 2x). Returns false while it has no size yet. */
function measure(inst: Instance): boolean {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.round(inst.canvas.clientWidth * dpr);
  const h = Math.round(inst.canvas.clientHeight * dpr);
  if (!w || !h) return false;
  if (w !== inst.width || h !== inst.height) {
    inst.canvas.width = inst.width = w;
    inst.canvas.height = inst.height = h;
    inst.camera.aspect = w / h;
    inst.camera.updateProjectionMatrix();
    inst.dirty = true;
  }
  return true;
}

/** On screen (with a margin), worked out from layout so it doesn't wait on an observer callback. */
function onScreen(inst: Instance): boolean {
  const r = inst.canvas.getBoundingClientRect();
  return r.bottom > -80 && r.top < innerHeight + 80 && r.right > -80 && r.left < innerWidth + 80 && r.width > 0;
}

/** Draws one frame. Returns true once something was actually drawn. */
function draw(inst: Instance): boolean {
  const r = getRenderer();
  if (!inst.width && !measure(inst)) return false;
  const w = inst.width;
  const h = inst.height;
  const size = r.getSize(new THREE.Vector2());
  if (size.x < w || size.y < h) r.setSize(Math.max(size.x, w), Math.max(size.y, h), false);
  const H = r.getSize(new THREE.Vector2()).y;
  const { m, mesh } = inst;
  mesh.rotation.set(m.rotX + m.lookY * BODY_SHARE, m.rotY + m.lookX * BODY_SHARE, 0);
  mesh.position.y = m.float;
  mesh.scale.set(1 + m.breath * 0.4, 1 + m.breath, 1);
  applyMotion(mesh.material, m);

  // Render into the top-left corner of the shared canvas, then copy that corner out.
  r.setScissorTest(true);
  r.setViewport(0, H - h, w, h);
  r.setScissor(0, H - h, w, h);
  r.clear();
  r.render(inst.scene, inst.camera);
  inst.ctx.clearRect(0, 0, w, h);
  inst.ctx.drawImage(r.domElement, 0, 0, w, h, 0, 0, w, h);
  inst.dirty = false;
  return true;
}

function setStatus(inst: Instance, status: Crew3DStatus) {
  playStatus(inst, inst.m, inst.mesh.material, status, () => {
    inst.dirty = true;
  });
  if (status === "error" || status === "off") {
    inst.ambient.pause();
    inst.glance.pause();
    gsap.to(inst.m, { lookX: 0, lookY: 0, duration: 0.5 });
  } else if (!reducedMotion()) {
    inst.ambient.resume();
    if (!pointer.active) inst.glance.resume();
  }
}

export interface MountOptions {
  source: Crew3DSource;
  status: Crew3DStatus;
  onReady?: () => void;
}

/** Attaches a 3D character to a canvas. Returns the handle for status updates and the cleanup. */
export function mountCrew3D(canvas: HTMLCanvasElement, { source, status, onReady }: MountOptions) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  getRenderer();

  const scene = new THREE.Scene();
  // A narrow lens, pulled back: the figure fills the frame with little perspective distortion.
  const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 10);
  camera.position.set(0, 0, 0.54 / Math.tan(THREE.MathUtils.degToRad(12)));
  const material = createCrewMaterial(source, { size: 1.1 });
  // Slightly larger than the frame, so turning never shows the plane's edge.
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.1, 144, 144), material);
  scene.add(mesh);

  const m = newMotion();
  const inst: Instance = {
    status: null,
    loops: [],
    load: null,
    canvas,
    ctx,
    scene,
    camera,
    mesh,
    m,
    ambient: ambientLoop(m),
    glance: glanceLoop(m),
    look: { x: gsap.quickTo(m, "lookX", { duration: 0.7, ease: "power3.out" }), y: gsap.quickTo(m, "lookY", { duration: 0.7, ease: "power3.out" }) },
    visible: false,
    ready: false,
    dirty: true,
    width: 0,
    height: 0,
    onReady,
    resize: new ResizeObserver(() => {
      measure(inst);
    }),
  };
  if (pointer.active) inst.glance.pause();
  inst.resize.observe(canvas);
  instances.add(inst);
  setStatus(inst, status);
  ensureTicker();

  // Textures download only when the character is about to be seen (scrolling carousels, long pages).
  inst.load = () => {
    loadCrewTextures(material, source)
      .then(() => {
        if (!instances.has(inst)) return;
        inst.ready = true;
        inst.dirty = true;
        // Hand over from the still image only once a frame is really on the canvas.
        const first = () => {
          if (!instances.has(inst)) return;
          if (draw(inst)) inst.onReady?.();
          else requestAnimationFrame(first);
        };
        first();
      })
      .catch(() => {
        /* The still image underneath stays in place. */
      });
  };
  if (onScreen(inst)) {
    inst.load();
    inst.load = null;
  }

  return {
    setStatus: (s: Crew3DStatus) => setStatus(inst, s),
    destroy: () => {
      instances.delete(inst);
      inst.loops.forEach((t) => t.kill());
      inst.ambient.kill();
      inst.glance.kill();
      gsap.killTweensOf(inst.m);
      inst.resize.disconnect();
      mesh.geometry.dispose();
      material.dispose();
      stopTickerIfIdle();
    },
  };
}
