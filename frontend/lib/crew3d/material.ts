/**
 * What every 3D crew member is made of, shared by the per-avatar engine and the landing stage:
 * the relief shader (depth displacement, a head rig that turns the head toward a target, key light,
 * cobalt rim, the running light sweep, an optional cut-out mask), the texture cache, and the GSAP
 * choreography for each run status.
 */

import gsap from "gsap";
import * as THREE from "three";

export type Crew3DStatus = "idle" | "running" | "done" | "your-turn" | "error" | "off";

export interface Crew3DSource {
  color: { idle: string; working: string };
  depth: { idle: string; working: string };
  /** Cut-out mask (white = figure). Only the landing stage uses it; portraits keep their backdrop. */
  mask?: { idle: string; working: string };
  /** Head centre in UV (0..1, y up) and radius, for the head rig. */
  head: { x: number; y: number; r: number };
}

/** Every animated number; GSAP tweens these, the renderer copies them into uniforms each frame. */
export interface Motion {
  rotX: number;
  rotY: number;
  /** Head turn toward the target: yaw (x) and pitch (y), radians. */
  lookX: number;
  lookY: number;
  float: number;
  breath: number;
  mix: number;
  sweep: number;
  rim: number;
  desat: number;
  pulse: number;
  fade: number;
}

export const newMotion = (): Motion => ({ rotX: 0, rotY: 0, lookX: 0, lookY: 0, float: 0, breath: 0, mix: 0, sweep: -1, rim: 0.28, desat: 0.08, pulse: 0, fade: 1 });

export const RIM: Record<Crew3DStatus, THREE.Color> = {
  idle: new THREE.Color("#4c7dff"),
  running: new THREE.Color("#6a93ff"),
  done: new THREE.Color("#3dd68c"),
  "your-turn": new THREE.Color("#f5b544"),
  error: new THREE.Color("#f2555a"),
  off: new THREE.Color("#636973"),
};

export const reducedMotion = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

const VERTEX = /* glsl */ `
  uniform sampler2D uDepthA;
  uniform sampler2D uDepthB;
  uniform float uMix;
  uniform float uRelief;
  uniform float uSize;
  uniform vec3 uHead;   // head centre (uv) and radius
  uniform vec2 uTurn;   // head yaw, pitch
  varying vec2 vUv;
  varying float vHead;

  vec3 turnY(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(v.x * c + v.z * s, v.y, -v.x * s + v.z * c); }
  vec3 turnX(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(v.x, v.y * c - v.z * s, v.y * s + v.z * c); }

  void main() {
    vUv = uv;
    float d = mix(texture2D(uDepthA, uv).r, texture2D(uDepthB, uv).r, uMix);
    vec3 p = position;
    p.z += (d - 0.15) * uRelief;

    // Head rig: the head (and, fading out, the neck) rotates about a pivot at the base of the neck.
    // Only the figure moves; the backdrop behind it stays put.
    vec2 q = uv - uHead.xy;
    q.y *= 0.82;
    float w = 1.0 - smoothstep(uHead.z * 0.9, uHead.z * 1.75, length(q));
    w *= smoothstep(0.28, 0.48, d) * smoothstep(uHead.y - uHead.z * 2.2, uHead.y - uHead.z * 0.9, uv.y);
    // A real head turns about a point well behind the face (roughly the top of the spine).
    vec3 pivot = vec3((uHead.x - 0.5) * uSize, (uHead.y - 0.5 - uHead.z * 1.05) * uSize, 0.55 * uRelief - uHead.z * uSize * 0.9);
    vec3 r = p - pivot;
    r = turnX(turnY(r, uTurn.x * w), uTurn.y * w);
    p = pivot + r;
    vHead = w;

    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`;

const FRAGMENT = /* glsl */ `
  uniform sampler2D uColorA;
  uniform sampler2D uColorB;
  uniform sampler2D uDepthA;
  uniform sampler2D uDepthB;
  uniform sampler2D uMaskA;
  uniform sampler2D uMaskB;
  uniform float uUseMask;
  uniform float uMix;
  uniform float uTexel;
  uniform float uRim;
  uniform vec3 uRimColor;
  uniform float uSweep;
  uniform float uDesat;
  uniform float uPulse;
  uniform float uFade;
  uniform vec2 uLight;
  uniform vec2 uTurn;
  uniform vec4 uMouth;  // mouth centre (uv), half width, how open (0 = closed: no effect at all)
  varying vec2 vUv;
  varying float vHead;

  float depthAt(vec2 uv) {
    return mix(texture2D(uDepthA, uv).r, texture2D(uDepthB, uv).r, uMix);
  }

  // Talking: the jaw region below the lips is sampled from slightly higher up, so the chin and lower lip drop;
  // the gap that opens between the lips gets a dark mouth interior. Off (open = 0) for every other character.
  vec2 jawUv(vec2 uv, out float inside) {
    inside = 0.0;
    if (uMouth.w <= 0.001) return uv;
    vec2 d = uv - uMouth.xy;
    float across = 1.0 - smoothstep(uMouth.z * 0.7, uMouth.z * 1.5, abs(d.x));
    float below = -d.y;
    float jaw = smoothstep(-0.002, 0.004, below) * (1.0 - smoothstep(0.045, 0.1, below));
    float drop = uMouth.w * 0.014 * across * jaw;
    float lips = 1.0 - smoothstep(0.0, 1.0, abs(d.x) / (uMouth.z * 0.92));
    inside = step(0.0, below) * step(below, drop * 0.8) * lips;
    return uv + vec2(0.0, drop);
  }

  void main() {
    float alpha = 1.0;
    float outline = 1.0;
    if (uUseMask > 0.5) {
      outline = mix(texture2D(uMaskA, vUv).r, texture2D(uMaskB, vUv).r, uMix);
      alpha = outline * smoothstep(0.0, 0.22, vUv.y); // busts dissolve into the floor instead of ending in a hard cut
      if (alpha < 0.02) discard;
    }
    float inside;
    vec2 cuv = jawUv(vUv, inside);
    vec3 col = mix(texture2D(uColorA, cuv).rgb, texture2D(uColorB, cuv).rgb, uMix);
    col = mix(col, vec3(0.16, 0.06, 0.06), inside * 0.82);
    float here = depthAt(vUv);

    // Surface normal from the depth gradient, so the scene lights relight the render as it turns.
    float dx = depthAt(vUv + vec2(uTexel, 0.0)) - depthAt(vUv - vec2(uTexel, 0.0));
    float dy = depthAt(vUv + vec2(0.0, uTexel)) - depthAt(vUv - vec2(0.0, uTexel));
    vec3 n = normalize(vec3(-dx * 6.0, -dy * 6.0, 1.0));

    // The key light stays in the room while the head turns under it.
    vec3 key = normalize(vec3(uLight.x - uTurn.x * vHead * 1.2, uLight.y + uTurn.y * vHead, 0.9));
    float diffuse = clamp(dot(n, key), 0.0, 1.0);
    col *= 0.94 + 0.2 * diffuse;

    // Cobalt rim where the surface turns away from the camera: silhouette and contours.
    float edge = pow(1.0 - clamp(n.z, 0.0, 1.0), 1.4) * smoothstep(0.25, 0.45, here);
    edge += (1.0 - smoothstep(0.35, 0.95, outline)) * 0.9 * uUseMask; // the silhouette, not the floor fade
    col += uRimColor * edge * (uRim + uPulse * 0.9) * 1.6;

    // Running: a band of cobalt light sweeps across the figure.
    float band = 1.0 - smoothstep(0.0, 0.09, abs(vUv.x * 0.65 + (1.0 - vUv.y) * 0.35 - uSweep));
    col += uRimColor * band * 0.3 * smoothstep(0.3, 0.5, here);

    float grey = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(grey), uDesat);
    float a = alpha * uFade;
    gl_FragColor = vec4(col * a, a);
  }
`;

export function createCrewMaterial(source: Crew3DSource, { size = 1.1, masked = false }: { size?: number; masked?: boolean } = {}) {
  return new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: masked,
    premultipliedAlpha: true,
    depthWrite: !masked,
    uniforms: {
      uColorA: { value: null },
      uColorB: { value: null },
      uDepthA: { value: null },
      uDepthB: { value: null },
      uMaskA: { value: null },
      uMaskB: { value: null },
      uUseMask: { value: masked ? 1 : 0 },
      uMix: { value: 0 },
      uRelief: { value: 0.12 },
      uSize: { value: size },
      uHead: { value: new THREE.Vector3(source.head.x, source.head.y, source.head.r) },
      uTurn: { value: new THREE.Vector2() },
      uTexel: { value: 2 / 512 },
      uRim: { value: 0.28 },
      uRimColor: { value: RIM.idle.clone() },
      uSweep: { value: -1 },
      uDesat: { value: 0.08 },
      uPulse: { value: 0 },
      uFade: { value: 1 },
      uLight: { value: new THREE.Vector2(-0.55, 0.45) },
      uMouth: { value: new THREE.Vector4(0.5, 0.5, 0.05, 0) },
    },
  });
}

/** Copies the animated numbers into the shader. */
export function applyMotion(material: THREE.ShaderMaterial, m: Motion) {
  const u = material.uniforms;
  u.uMix.value = m.mix;
  u.uSweep.value = m.sweep;
  u.uRim.value = m.rim;
  u.uDesat.value = m.desat;
  u.uPulse.value = m.pulse;
  u.uFade.value = m.fade;
  u.uTurn.value.set(m.lookX, m.lookY);
}

const textures = new Map<string, Promise<THREE.Texture>>();
const loader = typeof window === "undefined" ? null : new THREE.TextureLoader();

function texture(url: string, color: boolean): Promise<THREE.Texture> {
  const key = `${color ? "c" : "d"}:${url}`;
  let t = textures.get(key);
  if (!t) {
    t = new Promise((resolve, reject) =>
      loader!.load(
        url,
        (tex) => {
          tex.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
          tex.anisotropy = 4;
          tex.minFilter = THREE.LinearMipmapLinearFilter;
          resolve(tex);
        },
        undefined,
        reject,
      ),
    );
    textures.set(key, t);
  }
  return t;
}

/** Loads a character's textures into its material. Textures are shared between every copy on the page. */
export async function loadCrewTextures(material: THREE.ShaderMaterial, source: Crew3DSource, masked = false) {
  const jobs = [texture(source.color.idle, true), texture(source.color.working, true), texture(source.depth.idle, false), texture(source.depth.working, false)];
  if (masked && source.mask) jobs.push(texture(source.mask.idle, false), texture(source.mask.working, false));
  const [ca, cb, da, db, ma, mb] = await Promise.all(jobs);
  const u = material.uniforms;
  u.uColorA.value = ca;
  u.uColorB.value = cb;
  u.uDepthA.value = da;
  u.uDepthB.value = db;
  if (ma && mb) {
    u.uMaskA.value = ma;
    u.uMaskB.value = mb;
  }
}

export interface StatusPlayer {
  status: Crew3DStatus | null;
  loops: gsap.core.Tween[];
}

/**
 * Plays a run status. Motion lives here, in GSAP; the shader only reads the numbers.
 * running: working pose, float, light sweep · done: a nod and a green flash · your-turn: amber pulse ·
 * error: red rim, desaturated, still · off: grey.
 */
export function playStatus(player: StatusPlayer, m: Motion, material: THREE.ShaderMaterial, status: Crew3DStatus, onChange?: () => void) {
  if (player.status === status) return;
  const prev = player.status;
  player.status = status;
  const still = reducedMotion();
  const ease = "power3.out";
  player.loops.forEach((t) => t.kill());
  player.loops = [];
  gsap.killTweensOf(m, "mix,rim,desat,float,pulse,sweep,rotX");
  material.uniforms.uRimColor.value.copy(RIM[status]);
  const dur = still ? 0 : 0.35;
  const mark = onChange ? () => onChange() : undefined;

  gsap.to(m, { mix: status === "running" ? 1 : 0, duration: dur, ease, onUpdate: mark });
  gsap.to(m, { desat: status === "error" ? 0.6 : status === "off" ? 1 : 0.08, duration: dur, ease, onUpdate: mark });
  gsap.to(m, { rim: status === "running" ? 0.55 : status === "error" ? 0.35 : 0.28, duration: dur, ease, onUpdate: mark });

  if (still || status === "error" || status === "off") {
    gsap.to(m, { float: 0, pulse: 0, sweep: -1, duration: dur, onUpdate: mark });
    onChange?.();
    return;
  }
  if (status === "running") {
    player.loops.push(gsap.fromTo(m, { float: -0.012 }, { float: 0.012, duration: 1.5, ease: "sine.inOut", yoyo: true, repeat: -1 }));
    player.loops.push(gsap.fromTo(m, { sweep: -0.25 }, { sweep: 1.25, duration: 2.4, ease: "none", repeat: -1, repeatDelay: 0.4 }));
  } else {
    gsap.to(m, { float: 0, sweep: -1, duration: 0.4, ease });
  }
  if (status === "your-turn") {
    player.loops.push(gsap.fromTo(m, { pulse: 0 }, { pulse: 0.55, duration: 1, ease: "sine.inOut", yoyo: true, repeat: -1 }));
  } else {
    gsap.to(m, { pulse: 0, duration: 0.3 });
  }
  if (status === "done" && prev && prev !== "done") {
    // A small nod and a green flash: the stage finished.
    gsap.timeline()
      .to(m, { rotX: 0.12, duration: 0.18, ease: "power2.out" })
      .to(m, { rotX: 0, duration: 0.5, ease: "elastic.out(1, 0.5)" });
    gsap.fromTo(m, { pulse: 0.8 }, { pulse: 0, duration: 0.9, ease: "power2.out" });
  }
}

/** Idle life: slow breathing and a gentle body sway, under everything else. */
export function ambientLoop(m: Motion) {
  return gsap
    .timeline({ repeat: -1, paused: reducedMotion() })
    .to(m, { breath: 0.007, duration: 2.2, ease: "sine.inOut", yoyo: true, repeat: 1 }, 0)
    .to(m, { rotY: 0.04, duration: 4.4, ease: "sine.inOut", yoyo: true, repeat: 1 }, 0);
}

/** Without a mouse (phones, or before the pointer moves), characters glance around on their own. */
export function glanceLoop(m: Motion) {
  return gsap.to(m, {
    lookX: "random(-0.3, 0.3)",
    lookY: "random(-0.08, 0.12)",
    duration: 1.4,
    ease: "sine.inOut",
    repeat: -1,
    repeatDelay: 2.2,
    repeatRefresh: true,
    paused: reducedMotion(),
  });
}
