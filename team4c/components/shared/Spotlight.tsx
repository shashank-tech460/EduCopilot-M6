"use client";

import { useRef } from "react";

import { cn } from "@/lib/utils";

interface SpotlightProps {
  children: React.ReactNode;
  className?: string;
  /** CSS color stop for the glow center, e.g. "oklch(0.62 0.22 288 / 0.18)". */
  color?: string;
}

/**
 * Phase 6H — a cursor-following radial glow, used behind the landing
 * hero and (sparingly, per "not everything glassmorphism") on premium
 * card surfaces. Implemented as a single pseudo-layer whose position is
 * driven by inline CSS custom properties updated on `pointermove` — no
 * per-frame React state, no animation library, GPU-cheap (a
 * background-image on a single absolutely-positioned div).
 *
 * Mouse-only by construction (`pointerType !== "mouse"` is ignored), so
 * touch devices simply never render the glow rather than having it stick
 * to a stale position — consistent with the "touch alternative for hover
 * effects" accessibility requirement (nothing is ever gated behind it).
 */
export function Spotlight({ children, className, color = "oklch(0.62 0.22 288 / 0.16)" }: SpotlightProps) {
  const ref = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "mouse") return;
    const el = ref.current;
    const glow = glowRef.current;
    if (!el || !glow) return;
    const rect = el.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;
    glow.style.background = `radial-gradient(500px circle at ${x}% ${y}%, ${color}, transparent 65%)`;
    glow.style.opacity = "1";
  }

  function handlePointerLeave() {
    const glow = glowRef.current;
    if (!glow) return;
    glow.style.opacity = "0";
  }

  return (
    <div
      ref={ref}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      className={cn("relative isolate", className)}
    >
      <div
        ref={glowRef}
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 rounded-[inherit] opacity-0 transition-opacity duration-[var(--duration-md)]"
      />
      {children}
    </div>
  );
}
