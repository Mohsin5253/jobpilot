/**
 * The landing page's 3D stage: the crew standing in depth on a lit grid floor, with drifting dust.
 * Every head tracks the pointer from its own position (so their gazes converge on it), the camera
 * drifts with the mouse, the crew rises in with a GSAP intro, and scrolling dollies the camera back.
 * Each crew member plays its status in the demo run that the rest of the page follows too.
 */

import gsap from "gsap";
import * as THREE from "three";

import { ambientLoop, applyMotion, createCrewMaterial, glanceLoop, loadCrewTextures, newMotion, playStatus, reducedMotion, type Crew3DSource, type Crew3DStatus, type Motion, type StatusPlayer } from "@/lib/crew3d/material";

export interface StageActorSpec {
  key: string;
  source: Crew3DSource;
  /** World position of the portrait's centre, and its height in world units. */
  pos: [number, number, number];
  scale: number;
}

interface Actor extends StatusPlayer {
  spec: StageActorSpec;
  mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
  m: Motion;
  rise: { y: number };
  look: { x: gsap.QuickToFunc; y: gsap.QuickToFunc };
  ambient: gsap.core.Timeline;
  glance: gsap.core.Tween;
}

const FLOOR_Y = -0.62;

const FLOOR_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime;
  varying vec3 vWorld;
  float line(float v, float w) { float f = abs(fract(v) - 0.5); return 1.0 - smoothstep(0.5 - w, 0.5, f); }
  void main() {
    vec2 g = vWorld.xz * 1.6;
    float grid = max(line(g.x + 0.5, 0.03), line(g.y + 0.5, 0.03));
    float dist = length(vWorld.xz * vec2(0.35, 0.55));
    float fade = 1.0 - smoothstep(0.3, 2.0, dist);
    // A slow pulse runs out from under the crew, like a signal leaving the hub.
    float ring = smoothstep(0.08, 0.0, abs(dist - mod(uTime * 0.35, 3.0))) * 0.45;
    float glow = (1.0 - smoothstep(0.0, 1.1, dist)) * 0.14;
    float a = (grid * (0.18 + ring) + glow) * fade;
    gl_FragColor = vec4(uColor * a, a);
  }
`;

const FLOOR_VERTEX = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 w = modelMatrix * vec4(position, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;

const DUST_VERTEX = /* glsl */ `
  uniform float uTime;
  uniform float uScale;
  attribute float aSeed;
  varying float vAlpha;
  void main() {
    vec3 p = position;
    p.y = mod(p.y + uTime * (0.05 + aSeed * 0.08) + 1.0, 3.0) - 1.0 + ${FLOOR_Y.toFixed(2)};
    p.x += sin(uTime * 0.3 + aSeed * 12.0) * 0.08;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = uScale * (0.6 + aSeed) / -mv.z;
    vAlpha = 0.25 + 0.5 * aSeed;
    gl_Position = projectionMatrix * mv;
  }
`;

const DUST_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = (1.0 - smoothstep(0.0, 0.5, d)) * vAlpha;
    gl_FragColor = vec4(uColor * a, a);
  }
`;

export interface StageHandle {
  setStatuses: (s: Record<string, Crew3DStatus>) => void;
  destroy: () => void;
}

export function mountStage(canvas: HTMLCanvasElement, specs: StageActorSpec[], onReady?: () => void): StageHandle | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, premultipliedAlpha: true, powerPreference: "high-performance" });
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 40);
  const base = new THREE.Vector3(0, 0.06, 3.9);
  const cam = { x: 0, y: 0, dolly: 0, intro: 1.2 };
  const camTo = { x: gsap.quickTo(cam, "x", { duration: 1.4, ease: "power3.out" }), y: gsap.quickTo(cam, "y", { duration: 1.4, ease: "power3.out" }) };

  // Floor grid and the glow pool under the crew.
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(16, 10),
    new THREE.ShaderMaterial({
      vertexShader: FLOOR_VERTEX,
      fragmentShader: FLOOR_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: new THREE.Color("#4c7dff") }, uTime: { value: 0 } },
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = FLOOR_Y;
  scene.add(floor);

  // Drifting dust in the light.
  const count = matchMedia("(pointer: coarse)").matches ? 90 : 220;
  const pos = new Float32Array(count * 3);
  const seed = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 7;
    pos[i * 3 + 1] = Math.random() * 3;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 3.5 - 0.4;
    seed[i] = Math.random();
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  dustGeo.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
  const dust = new THREE.Points(
    dustGeo,
    new THREE.ShaderMaterial({
      vertexShader: DUST_VERTEX,
      fragmentShader: DUST_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uScale: { value: 9 * renderer.getPixelRatio() }, uColor: { value: new THREE.Color("#9db8ff") } },
    }),
  );
  scene.add(dust);

  const actors: Actor[] = specs.map((spec) => {
    const material = createCrewMaterial(spec.source, { size: 1, masked: true });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1, 112, 112), material);
    mesh.scale.setScalar(spec.scale);
    mesh.position.set(...spec.pos);
    // Each one angled a little toward the centre of the group.
    mesh.rotation.y = -spec.pos[0] * 0.09;
    scene.add(mesh);
    const m = newMotion();
    m.fade = 0;
    const a: Actor = {
      spec,
      mesh,
      m,
      rise: { y: -0.35 },
      status: null,
      loops: [],
      look: { x: gsap.quickTo(m, "lookX", { duration: 0.8, ease: "power3.out" }), y: gsap.quickTo(m, "lookY", { duration: 0.8, ease: "power3.out" }) },
      ambient: ambientLoop(m),
      glance: glanceLoop(m),
    };
    a.glance.pause();
    return a;
  });

  const pointer = { nx: 0, ny: 0, active: false };
  const onPointer = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    pointer.nx = (e.clientX / innerWidth) * 2 - 1;
    pointer.ny = (e.clientY / innerHeight) * 2 - 1;
    if (!pointer.active) {
      pointer.active = true;
      actors.forEach((a) => a.glance.pause());
    }
  };
  window.addEventListener("pointermove", onPointer, { passive: true });

  const resize = () => {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Narrow screens: pull back so the whole group fits.
    base.z = camera.aspect < 1 ? 5.2 : camera.aspect < 1.3 ? 4.5 : 4.2;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  const still = reducedMotion();
  const target = new THREE.Vector3();
  const ray = new THREE.Raycaster();
  const lookPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -2.2); // z = 2.2, in front of the crew
  const head = new THREE.Vector3();
  let frame = 0;
  let ready = false;

  const render = () => {
    const t = performance.now() / 1000;
    floor.material.uniforms.uTime.value = t;
    dust.material.uniforms.uTime.value = t;

    // Scroll dolly: as the hero leaves the screen the camera rises and pulls back.
    const r = canvas.getBoundingClientRect();
    cam.dolly = gsap.utils.clamp(0, 1, -r.top / Math.max(r.height, 1));
    camera.position.set(base.x + cam.x, base.y + cam.y + cam.dolly * 0.5, base.z + cam.intro + cam.dolly * 1.4);
    camera.lookAt(0, 0.16 + cam.dolly * 0.2, 0);

    if (!still && pointer.active) {
      camTo.x(pointer.nx * 0.35);
      camTo.y(-pointer.ny * 0.15);
      ray.setFromCamera(new THREE.Vector2(pointer.nx, -pointer.ny), camera);
      ray.ray.intersectPlane(lookPlane, target);
    }
    for (const a of actors) {
      const { m, mesh, spec } = a;
      mesh.position.y = spec.pos[1] + a.rise.y + m.float * spec.scale;
      mesh.rotation.x = m.rotX;
      mesh.scale.set(spec.scale * (1 + m.breath * 0.4), spec.scale * (1 + m.breath), spec.scale);
      if (!still && pointer.active && a.status !== "error") {
        // Aim from this actor's own head, so the crew's gazes converge on the pointer.
        head.set(spec.pos[0] + (spec.source.head.x - 0.5) * spec.scale, mesh.position.y + (spec.source.head.y - 0.5) * spec.scale, spec.pos[2]);
        const dz = Math.max(target.z - head.z, 0.4);
        a.look.x(gsap.utils.clamp(-0.5, 0.5, Math.atan2(target.x - head.x, dz) + spec.pos[0] * 0.09));
        a.look.y(gsap.utils.clamp(-0.22, 0.28, -Math.atan2(target.y - head.y, dz)));
      }
      applyMotion(mesh.material, m);
    }
    renderer.render(scene, camera);
  };

  const tick = () => {
    if (!ready || document.hidden) return;
    const r = canvas.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) return; // off screen: nothing to draw
    if (matchMedia("(pointer: coarse)").matches && frame++ % 2) return;
    render();
  };
  gsap.ticker.add(tick);

  Promise.all(actors.map((a) => loadCrewTextures(a.mesh.material, a.spec.source, true)))
    .then(() => {
      ready = true;
      // Intro: the crew rises in from the centre outward while the camera settles.
      const order = [...actors].sort((x, y) => Math.abs(x.spec.pos[0]) - Math.abs(y.spec.pos[0]));
      if (still) {
        actors.forEach((a) => ((a.rise.y = 0), (a.m.fade = 1)));
        cam.intro = 0;
      } else {
        const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
        tl.to(cam, { intro: 0, duration: 2.2, ease: "power2.out" }, 0);
        order.forEach((a, i) => {
          tl.to(a.rise, { y: 0, duration: 1.1 }, 0.15 + i * 0.12);
          tl.to(a.m, { fade: 1, duration: 0.9 }, 0.15 + i * 0.12);
        });
        tl.call(() => {
          if (!pointer.active) actors.forEach((a) => a.glance.resume());
        });
      }
      render();
      onReady?.();
    })
    .catch(() => {
      /* The poster image stays. */
    });

  return {
    setStatuses: (s) => {
      for (const a of actors) {
        const st = s[a.spec.key] ?? "idle";
        playStatus(a, a.m, a.mesh.material, st);
        if (st === "error") a.glance.pause();
      }
      if (still && ready) render();
    },
    destroy: () => {
      gsap.ticker.remove(tick);
      window.removeEventListener("pointermove", onPointer);
      ro.disconnect();
      actors.forEach((a) => {
        a.loops.forEach((t) => t.kill());
        a.ambient.kill();
        a.glance.kill();
        gsap.killTweensOf(a.m);
        gsap.killTweensOf(a.rise);
        a.mesh.geometry.dispose();
        a.mesh.material.dispose();
      });
      gsap.killTweensOf(cam);
      floor.geometry.dispose();
      floor.material.dispose();
      dustGeo.dispose();
      dust.material.dispose();
      renderer.dispose();
    },
  };
}
