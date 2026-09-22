import Link from "next/link";
import { FileText, GraduationCap, MessageSquare, PlayCircle, Sparkles } from "lucide-react";

import { TiltCard } from "@/components/shared/TiltCard";

/**
 * Layout for the (auth) route group.
 * Real Auth.js wiring happens in Phase 4 — this only establishes the route
 * group structure approved in Phase 1.
 *
 * Phase 6E: added a branded visual panel (lg+ only, purely decorative —
 * the actual login/signup forms and their field labels/ids are completely
 * unchanged, so nothing here affects the existing E2E flows in
 * tests/e2e/helpers.ts, which only interact with the form itself).
 *
 * Phase 6H: extended the panel with the same aurora/floating-card visual
 * language as the landing hero (app/page.tsx) — a document card, a video
 * card, and an AI-answer-with-citation card — so the product identity is
 * consistent from the very first screen a visitor sees, not just the
 * marketing page. Purely decorative (`aria-hidden`); the form itself is
 * completely untouched.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-full flex-1 lg:grid-cols-2">
      <div className="aurora-bg ambient-grid relative hidden flex-col justify-between overflow-hidden border-r border-border/60 p-10 lg:flex">
        <Link href="/" className="relative z-10 flex items-center gap-2 font-semibold tracking-tight">
          <GraduationCap className="h-5 w-5 text-brand-indigo" aria-hidden="true" />
          EduCopilot
        </Link>

        <div className="relative z-10 flex flex-col gap-6">
          <blockquote className="max-w-sm text-xl font-medium leading-relaxed tracking-tight text-foreground">
            &ldquo;Every answer traces back to the{" "}
            <span className="text-gradient-brand">page or moment</span> it actually came from.&rdquo;
          </blockquote>
          <div className="flex flex-col gap-3 text-sm text-muted-foreground">
            <div className="flex items-center gap-2.5">
              <FileText className="h-4 w-4 text-brand-indigo" aria-hidden="true" />
              Grounded answers from your own PDFs and videos
            </div>
            <div className="flex items-center gap-2.5">
              <MessageSquare className="h-4 w-4 text-brand-indigo" aria-hidden="true" />
              A conversational AI tutor that cites its sources
            </div>
            <div className="flex items-center gap-2.5">
              <Sparkles className="h-4 w-4 text-brand-indigo" aria-hidden="true" />
              Organized, isolated workspaces per course
            </div>
          </div>
        </div>

        {/* Floating product-preview cards — same technique as the landing
            hero, scaled for this narrower panel. */}
        <div className="pointer-events-none relative z-10 hidden h-40 xl:block" aria-hidden="true">
          <TiltCard className="animate-hero-float-a absolute left-0 top-0 w-44 rounded-lg border border-border/60 bg-card p-2.5 shadow-[var(--shadow-lg)]" maxTilt={5}>
            <div className="flex items-center gap-1.5 text-[0.65rem] font-medium text-muted-foreground">
              <FileText className="h-3 w-3 text-brand-indigo" />
              Lecture-Notes.pdf
            </div>
          </TiltCard>
          <TiltCard className="animate-hero-float-c absolute left-28 top-6 w-36 rounded-lg border border-border/60 bg-card p-2.5 shadow-[var(--shadow-lg)]" maxTilt={5}>
            <div className="flex items-center gap-1.5 text-[0.65rem] font-medium text-muted-foreground">
              <PlayCircle className="h-3 w-3 text-brand-cyan" />
              Lecture 03
            </div>
          </TiltCard>
          <TiltCard className="animate-hero-float-b glass-panel absolute bottom-0 left-8 w-48 rounded-lg p-2.5 shadow-[var(--shadow-lg)]" maxTilt={5}>
            <div className="mb-1 flex items-center gap-1.5 text-[0.65rem] font-medium text-muted-foreground">
              <Sparkles className="h-3 w-3 text-brand-indigo" />
              Answer
            </div>
            <span className="inline-flex items-center rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[0.6rem] font-medium text-brand-indigo underline underline-offset-2">
              Lecture-Notes.pdf · Page 9
            </span>
          </TiltCard>
        </div>

        <p className="relative z-10 text-xs text-muted-foreground">Educational Intelligence Copilot</p>
      </div>
      <div className="flex flex-1 items-center justify-center px-4 py-16">{children}</div>
    </div>
  );
}
