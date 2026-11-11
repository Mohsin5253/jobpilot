/**
 * The mock interviewer: one crew portrait as a 3D talking head, with its own renderer (the interview page shows
 * exactly one). Same relief shader and head rig as the crew, plus:
 * - a jaw that opens and closes while the interviewer speaks (driven by the speech engine's word boundaries,
 *   with natural flutter between them), and nods at the end of each sentence;
 * - while the candidate answers, an attentive pose: head slightly tilted toward the answer, a small nod now and
 *   then as they type or speak;
 * - the head follows the pointer, and idles with breathing and glances like every crew member.
 */

import gsap from "gsap";
import * as THREE from "three";

import { ambientLoop, applyMotion, createCrewMaterial, glanceLoop, loadCrewTextures, newMotion, reducedMotion, type Crew3DSource } from "@/lib/crew3d/material";

export interface Mouth {
  x: number;
  y: number;
  w: number;
}

export interface Talker {
  speakStart: () => void;
  speakWord: () => void;
  speakEnd: () => void;
  listen: (on: boolean) => void;
  nod: () => void;
  destroy: () => void;
}

export function mountTalker(canvas: HTMLCanvasElement, source: Crew3DSource, mouth: Mouth, onReady?: () => void): Talker | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, premultipliedAlpha: true });
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 10);
  camera.position.set(0, 0, 0.54 / Math.tan(THREE.MathUtils.degToRad(12)));
  const material = createCrewMaterial(source, { size: 1.1 });
  material.uniforms.uMouth.value.set(mouth.x, mouth.y, mouth.w, 0);
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.1, 192, 192), material);
  scene.add(mesh);

  const m = newMotion();
  const still = reducedMotion();
  const ambient = ambientLoop(m);
  const glance = glanceLoop(m);
  const jaw = { open: 0, target: 0, speaking: false, listening: false, tilt: 0 };
  const look = { x: gsap.quickTo(m, "lookX", { duration: 0.8, ease: "power3.out" }), y: gsap.quickTo(m, "lookY", { duration: 0.8, ease: "power3.out" }) };
  let pointerActive = false;
  let ready = false;
  let flutter = 0;

  const onPointer = (e: PointerEvent) => {
    if (e.pointerType !== "mouse" || still) return;
    pointerActive = true;
    glance.pause();
    const r = canvas.getBoundingClientRect();
    const nx = gsap.utils.clamp(-1, 1, (e.clientX - (r.left + r.width / 2)) / Math.max(innerWidth * 0.5, 1));
    const ny = gsap.utils.clamp(-1, 1, (e.clientY - (r.top + r.height * 0.32)) / Math.max(innerHeight * 0.6, 1));
    look.x(nx * 0.32 + jaw.tilt);
    look.y(ny * 0.14);
  };
  window.addEventListener("pointermove", onPointer, { passive: true });

  const resize = () => {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  const tick = (_t: number, dt: number) => {
    if (!ready || document.hidden) return;
    // Speech: the jaw chases a target that word boundaries kick open; between words it flutters like real speech.
    if (jaw.speaking && !still) {
      flutter += dt / 1000;
      const syllables = 0.35 + 0.35 * Math.abs(Math.sin(flutter * 11.5)) + 0.3 * Math.abs(Math.sin(flutter * 4.3 + 1.2));
      jaw.target = Math.max(jaw.target * 0.9, syllables * 0.85);
    } else {
      jaw.target *= 0.8;
    }
    jaw.open += (jaw.target - jaw.open) * Math.min(1, dt / 55);
    material.uniforms.uMouth.value.w = jaw.open < 0.01 ? 0 : jaw.open;
    mesh.rotation.set(m.rotX + m.lookY * 0.18, m.rotY + m.lookX * 0.18, jaw.listening ? -0.025 : 0);
    mesh.position.y = m.float;
    mesh.scale.set(1 + m.breath * 0.4, 1 + m.breath, 1);
    applyMotion(material, m);
    renderer.render(scene, camera);
  };
  gsap.ticker.add(tick);

  loadCrewTextures(material, source)
    .then(() => {
      ready = true;
      renderer.render(scene, camera);
      onReady?.();
    })
    .catch(() => {
      /* the still portrait underneath stays */
    });

  const nod = () => {
    if (still) return;
    gsap.timeline().to(m, { lookY: 0.12, duration: 0.22, ease: "power2.out" }).to(m, { lookY: 0, duration: 0.35, ease: "power2.inOut" });
  };

  const api: Talker = {
    speakStart: () => {
      jaw.speaking = true;
      flutter = 0;
      jaw.tilt = 0;
      if (!pointerActive) glance.pause();
      gsap.to(m, { lookX: 0, lookY: 0, duration: 0.5 });
    },
    speakWord: () => {
      jaw.target = Math.min(1, jaw.target + 0.55);
    },
    speakEnd: () => {
      jaw.speaking = false;
      nod();
      if (!pointerActive && !still) glance.resume();
    },
    listen: (on: boolean) => {
      jaw.listening = on;
      jaw.tilt = on ? 0.12 : 0;
      if (!pointerActive) gsap.to(m, { lookX: jaw.tilt, duration: 0.8, ease: "power2.out" });
    },
    nod,
    destroy: () => {
      gsap.ticker.remove(tick);
      window.removeEventListener("pointermove", onPointer);
      ro.disconnect();
      ambient.kill();
      glance.kill();
      gsap.killTweensOf(m);
      mesh.geometry.dispose();
      material.dispose();
      renderer.dispose();
    },
  };
  // Development only: lets the talking animation be driven from the console without speech audio.
  if (process.env.NODE_ENV !== "production") (canvas as HTMLCanvasElement & { __talker?: Talker }).__talker = api;
  return api;
}
