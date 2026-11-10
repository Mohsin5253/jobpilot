"use client";

import { Check, X } from "lucide-react";
import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useCrewStatus } from "@/components/agents/crew-status";
import { AGENTS, agentAlt, type CrewKey } from "@/config/agents";
import { crew3DSupported } from "@/lib/crew3d/support";
import { cn } from "@/lib/utils";

// Three.js loads only on pages that show a character large enough to be 3D.
const Agent3D = dynamic(() => import("@/components/agents/agent-3d"), { ssr: false });

export type AgentStatus = "idle" | "running" | "done" | "your-turn" | "error" | "off";

export interface AgentAvatarProps {
  agent: CrewKey;
  /** Leave unset to follow the page's shared run state (the live run in the app, the demo run on the landing page). */
  status?: AgentStatus;
  /** 24 inline · 32–40 lists/toasts · 64 flight path · 96 popovers · 160–200 console/empty states · 320–480 landing */
  size?: number;
  /** "tile": squircle with the agent-tint backdrop (default). "plain": no frame (large hero moments). */
  variant?: "tile" | "plain";
  /** Next to the agent's visible name the image is decorative (alt=""). */
  decorative?: boolean;
  /** Preload: only for the one large character of a view. */
  priority?: boolean;
  /** The "you" stage: the user's photo or initials. */
  user?: { name?: string | null; photo?: string | null };
  /** Fill the parent instead of a fixed box: the parent sets the size per breakpoint. `size` then only picks crop and badge. */
  fluid?: boolean;
  /** Responsive `sizes` for next/image when `fluid`. */
  sizes?: string;
  className?: string;
}

const FACE_CROP_MAX = 40;
/** From this size up, characters are live 3D; smaller ones (lists, toasts, the sidebar) stay still renders. */
const MIN_3D = 56;

function initials(name?: string | null) {
  return (name || "You").split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

/**
 * The only way crew characters are rendered. Status is layered in code on top of the artwork:
 * idle (still, slightly desaturated) · running (working image, float, cobalt light sweep) ·
 * done (green check, one bounce) · your-turn (amber ring pulse) · error (red badge, desaturated, still).
 */
export function AgentAvatar({ agent, status: given, size = 40, variant = "tile", decorative = false, priority = false, user, fluid = false, sizes, className }: AgentAvatarProps) {
  const live = useCrewStatus(agent);
  const status: AgentStatus = given ?? live ?? "idle";
  const isYou = agent === "you";
  const cfg = isYou ? null : AGENTS[agent];
  const running = status === "running";
  const faceCrop = size <= FACE_CROP_MAX;
  const tint = isYou ? "var(--tint-you)" : cfg!.tint;
  const label = isYou ? "You, the final member of the crew" : agentAlt(cfg!.key);

  const imgStyle: CSSProperties = cfg
    ? faceCrop
      ? { objectPosition: `${cfg.face.x}% ${cfg.face.y}%`, transform: `scale(${cfg.face.zoom})`, transformOrigin: `${cfg.face.x}% ${cfg.face.y}%` }
      : { objectPosition: "50% 18%" }
    : {};
  const filter = status === "error" ? "saturate(0.4)" : status === "off" ? "grayscale(1)" : status === "idle" ? "saturate(0.9)" : undefined;
  const badge = Math.max(14, Math.round(size * 0.3));
  const [can3D, setCan3D] = useState(false);
  const [live3D, setLive3D] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  // 3D only while the avatar is actually laid out: copies hidden at this breakpoint (display: none)
  // never download textures or take a slot in the renderer.
  useEffect(() => {
    const el = box.current;
    if (!el || !cfg || !(fluid || size >= MIN_3D) || !crew3DSupported()) return setCan3D(false);
    const check = () => setCan3D(el.getClientRects().length > 0 && el.clientWidth > 0);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [cfg, fluid, size]);

  return (
    <span
      ref={box}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : `${label}${status !== "idle" ? ` (${status.replace("-", " ")})` : ""}`}
      aria-hidden={decorative || undefined}
      className={cn("relative inline-block shrink-0 align-middle", running && !live3D && "animate-float", status === "off" && "opacity-55", className)}
      style={fluid ? { width: "100%", height: "100%" } : { width: size, height: size }}
    >
      <span
        className={cn("absolute inset-0 overflow-hidden", variant === "tile" && "rounded-[var(--radius-avatar)] [corner-shape:squircle]")}
        style={
          variant === "tile"
            ? { background: `radial-gradient(120% 90% at 50% 0%, color-mix(in oklab, ${tint} 14%, transparent), transparent 70%), #111316` }
            : undefined
        }
      >
        {cfg ? (
          <>
            <Image
              src={cfg.images.idle}
              alt=""
              fill
              sizes={sizes ?? `${size}px`}
              priority={priority}
              className="object-cover mix-blend-lighten transition-opacity duration-200"
              style={{ ...imgStyle, filter, opacity: running || live3D ? 0 : 1 }}
            />
            {running && !live3D && (
              <Image src={cfg.images.working} alt="" fill sizes={sizes ?? `${size}px`} className="object-cover mix-blend-lighten" style={{ ...imgStyle, animation: "fade-in 200ms var(--ease) both" }} />
            )}
            {can3D && <Agent3D agent={cfg.key} status={status} onReady={() => setLive3D(true)} />}
          </>
        ) : user?.photo ? (
          <Image src={user.photo} alt="" fill sizes={sizes ?? `${size}px`} className="object-cover" />
        ) : (
          <span className="grid size-full place-items-center bg-[linear-gradient(160deg,#1a2342,#111316)] font-semibold tracking-tight text-[#e6ecff]" style={{ fontSize: size * 0.36 }}>
            {initials(user?.name)}
          </span>
        )}
        {variant === "tile" && <span aria-hidden className="pointer-events-none absolute inset-0 rounded-[inherit] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]" />}
      </span>

      {/* Running: a cobalt light sweeps round the frame. */}
      {running && variant === "tile" && (
        <span aria-hidden className="sweep-ring pointer-events-none absolute -inset-[2px] rounded-[var(--radius-avatar)] [corner-shape:squircle]" />
      )}
      {/* Your turn: amber ring pulse. "You" otherwise wears a cobalt ring. */}
      {(status === "your-turn" || isYou) && (
        <span
          aria-hidden
          className={cn("pointer-events-none absolute -inset-[3px] rounded-[var(--radius-avatar)] [corner-shape:squircle]", status === "your-turn" && "animate-ring-pulse")}
          style={status === "your-turn" ? undefined : { boxShadow: "0 0 0 2px var(--cobalt)" }}
        />
      )}
      {(status === "done" || status === "error") && (
        <span
          key={status}
          aria-hidden
          className={cn(
            "absolute -right-1 -bottom-1 grid place-items-center rounded-full border-2 border-[var(--surface)] text-white",
            status === "done" ? "animate-bounce-once bg-[var(--done)]" : "bg-[var(--error)]",
          )}
          style={fluid ? { width: "26%", height: "26%" } : { width: badge, height: badge }}
        >
          {status === "done" ? <Check className="size-[62%]" strokeWidth={3} /> : <X className="size-[62%]" strokeWidth={3} />}
        </span>
      )}
    </span>
  );
}

/** Large hero moments (console, empty states): the character with one soft cobalt glow behind it. */
export function AgentHero({
  agent,
  status,
  size = 180,
  priority = true,
  fluid = false,
  sizes,
  className,
}: {
  agent: CrewKey;
  /** Leave unset to follow the page's shared run state (the live run in the app, the demo run on the landing page). */
  status?: AgentStatus;
  size?: number;
  priority?: boolean;
  fluid?: boolean;
  sizes?: string;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-grid shrink-0 place-items-center", className)} style={fluid ? { width: "100%", height: "100%" } : { width: size, height: size }}>
      <span aria-hidden className="pointer-events-none absolute -inset-[30%]" style={{ background: "var(--glow-cobalt)" }} />
      <AgentAvatar agent={agent} status={status} size={size} priority={priority} fluid={fluid} sizes={sizes} />
    </span>
  );
}
