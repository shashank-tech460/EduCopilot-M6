"use client";

import { useRef } from "react";

import { cn } from "@/lib/utils";

interface TiltCardProps {
  children: React.ReactNode;
  className?: string;
  /** Maximum rotation in degrees. Small by design — this is a "premium
   * subtlety" effect, not a toy. */
  maxTilt?: number;
}

/**
 * Phase 6H — a small, reusable perspective-tilt wrapper for dashboard/
 * workspace/landing cards ("hover: subtle perspective, slight lift" per
 * the master prompt, explicitly warning against spinning/excessive
 * motion). Pure CSS transform driven by inline custom properties set on
 * pointer move — no React re-render per frame, no animation library.
 *
 * Uses `.tilt-card` (app/globals.css), which itself does nothing extra
 * under `prefers-reduced-motion: reduce` (forced to `transform: none`),
 * so this component never needs to check that media query itself — the
 * CSS layer already owns that responsibility, consistent with how every
 * other decorative effect in this app is gated.
 *
 * Touch/pointer without hover capability (most touchscreens) never fires
 * `pointermove` the same way, so the card simply never tilts there —
 * exactly the desired "touch alternative for hover effects" behavior
 * (Phase 6H §12): no interaction is ever gated behind the tilt itself.
 */
export function TiltCard({ children, className, maxTilt = 6 }: TiltCardProps) {
  const ref = useRef<HTMLDivElement>(null);

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "mouse") return;
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width; // 0..1
    const py = (event.clientY - rect.top) / rect.height; // 0..1
    const rotateY = (px - 0.5) * (maxTilt * 2);
    const rotateX = (0.5 - py) * (maxTilt * 2);
    el.style.setProperty("--tilt-x", `${rotateX.toFixed(2)}deg`);
    el.style.setProperty("--tilt-y", `${rotateY.toFixed(2)}deg`);
  }

  function handlePointerLeave() {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--tilt-x", "0deg");
    el.style.setProperty("--tilt-y", "0deg");
  }

  return (
    <div
      ref={ref}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      className={cn("tilt-card", className)}
    >
      {children}
    </div>
  );
}
