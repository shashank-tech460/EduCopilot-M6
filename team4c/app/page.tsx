import Link from "next/link";
import {
  ArrowRight,
  FileText,
  FolderKanban,
  MessageSquare,
  PlayCircle,
  ShieldCheck,
  Sparkles,
  Upload,
  Video,
} from "lucide-react";

import { SiteNav } from "@/components/shared/site-nav";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spotlight } from "@/components/shared/Spotlight";
import { TiltCard } from "@/components/shared/TiltCard";

interface Feature {
  icon: typeof Upload;
  title: string;
  description: string;
}

const FEATURES: Feature[] = [
  {
    icon: Upload,
    title: "Course Material",
    description: "Upload PDFs and lecture videos into one organized workspace.",
  },
  {
    icon: Video,
    title: "YouTube Lectures",
    description: "Add YouTube links alongside your other course material.",
  },
  {
    icon: FolderKanban,
    title: "Organized Workspaces",
    description: "Keep material separated by course or subject, all in one place.",
  },
  {
    icon: MessageSquare,
    title: "AI Tutor",
    description: "Ask questions about your material and get answers grounded in it.",
  },
];

interface Step {
  number: string;
  title: string;
  description: string;
}

const STEPS: Step[] = [
  {
    number: "1",
    title: "Create a workspace",
    description: "Set up a workspace for a course or subject in a few seconds.",
  },
  {
    number: "2",
    title: "Add your course material",
    description: "Upload PDFs, MP4 lecture recordings, or link YouTube videos.",
  },
  {
    number: "3",
    title: "Ask questions and learn",
    description: "Get answers from your AI tutor, grounded in what you uploaded.",
  },
];

interface TrustPoint {
  icon: typeof ShieldCheck;
  title: string;
  description: string;
}

const TRUST_POINTS: TrustPoint[] = [
  {
    icon: FileText,
    title: "Grounded, not guessed",
    description: "Every answer traces back to a specific page or moment in your own material.",
  },
  {
    icon: FolderKanban,
    title: "Workspace isolation",
    description: "Each workspace's material stays scoped to that workspace — nothing leaks across courses or accounts.",
  },
  {
    icon: ShieldCheck,
    title: "Your material, your account",
    description: "Only you can see what you upload. Materials and conversations are never shared across accounts.",
  },
];

import { auth } from "@/lib/auth";

export default async function Home() {
  const session = await auth();

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <SiteNav />

      <main className="flex-1">
        {/* Hero */}
        <section className="aurora-bg ambient-grid relative overflow-hidden border-b border-border/60">
          {/* Phase 6K: below `lg:` (1024px), the floating product-card
              visual is hidden entirely (it's tuned for the two-column
              desktop layout and would need real repositioning to work
              standalone), so the section's desktop-generous vertical
              padding (originally py-20/py-28 even on mobile/tablet) left
              a large, genuinely empty dark gap between the CTA buttons
              and the next section — confirmed live at 375/390/768px, not
              assumed. Tightened for everything below `lg:`; desktop
              padding (which has the floating cards to balance) is
              unchanged. */}
          <Spotlight className="mx-auto grid w-full max-w-6xl items-center gap-12 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-2 lg:py-32">
            <div className="flex flex-col items-center gap-6 text-center lg:items-start lg:text-left">
              <span
                className="animate-fade-up-in inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card/60 px-3 py-1 text-xs font-medium text-muted-foreground glass-panel"
                style={{ animationDelay: "0ms" }}
              >
                <Sparkles className="h-3.5 w-3.5 text-brand-indigo" aria-hidden="true" />
                Source-grounded AI tutoring
              </span>
              {/* M6 final polish: the gradient span (Phase 6K shortened it
                  to "course material", down from a 3-word run in Phase
                  6H/6I) was mathematically proven compliant — every
                  interpolated point measured 6.04-11.07:1 contrast
                  against the background — but continued to read as
                  harder to make out than the rest of the headline in
                  real use. Per this phase's explicit instruction ("if
                  the gradient causes ANY readability problem at any
                  viewport, remove it completely — premium is more
                  important than a decorative effect"), the gradient is
                  removed from the headline outright. The whole headline
                  is now plain `text-foreground` — the same token used
                  for ordinary page text, already verified at 16.6:1 on
                  `--card` and never in question. Brand color/gradient
                  still appears throughout the page (badge icon, floating
                  cards, feature icons, CTA glow) — only the headline
                  itself no longer risks it. */}
              <h1
                className="animate-fade-up-in max-w-2xl text-4xl font-semibold tracking-tight text-foreground sm:text-5xl lg:text-6xl"
                style={{ animationDelay: "80ms" }}
              >
                Learn from your own course material.
              </h1>
              <p
                className="animate-fade-up-in max-w-xl text-balance text-lg text-muted-foreground"
                style={{ animationDelay: "160ms" }}
              >
                Upload PDFs, lecture videos, and YouTube links into one workspace.
                Ask questions about your material and get answers grounded in
                what you&apos;ve actually studied.
              </p>
              <div className="animate-fade-up-in mt-2 flex flex-col gap-3 sm:flex-row" style={{ animationDelay: "240ms" }}>
                {session?.user ? (
                  <Button asChild size="lg" className="glow-primary">
                    <Link href="/dashboard">
                      Open Dashboard
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </Button>
                ) : (
                  <>
                    <Button asChild size="lg" className="glow-primary">
                      <Link href="/signup">
                        Get Started
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button asChild size="lg" variant="outline">
                      <Link href="/login">Sign In</Link>
                    </Button>
                  </>
                )}
              </div>

              {/* M6 final polish: below `lg:`, the full floating-card
                  visual (further down) is hidden entirely — it's
                  absolutely positioned and tuned for the two-column
                  desktop layout, so it would need real rework to appear
                  standalone. That previously left mobile/tablet with
                  only text and no supporting visual at all. This is a
                  single, compact, inline (not absolutely positioned)
                  product-snapshot card — real proportions, no repeated
                  floating pieces — shown only below `lg:` so it doesn't
                  duplicate the fuller desktop visual. */}
              <div
                className="animate-fade-up-in glass-panel mt-2 w-full max-w-sm rounded-xl p-4 text-left lg:hidden"
                style={{ animationDelay: "280ms" }}
                aria-hidden="true"
              >
                <div className="flex items-center gap-4 text-xs font-medium text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <FileText className="h-3.5 w-3.5 text-brand-indigo" />
                    PDF
                  </span>
                  <span className="flex items-center gap-1.5">
                    <PlayCircle className="h-3.5 w-3.5 text-brand-indigo" />
                    Video
                  </span>
                  <span className="flex items-center gap-1.5">
                    <MessageSquare className="h-3.5 w-3.5 text-brand-indigo" />
                    Tutor
                  </span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-foreground">
                  Normalization reduces redundancy by organizing data into related tables…
                </p>
                <span className="mt-2 inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[0.65rem] font-medium text-brand-indigo underline underline-offset-2">
                  Course-Notes.pdf · Page 4
                </span>
              </div>
            </div>

            {/* Product-preview visual — CSS/DOM only, no WebGL dependency
                (see docs/PHASE_6E_UI_UX_AUDIT.md §13 for the reasoning,
                reaffirmed for Phase 6H's "tasteful 3D" brief). Purely
                decorative; hidden from screen readers since it conveys
                nothing beyond what the copy already states. Each card
                gets its own idle float (CSS keyframes) plus a real,
                pointer-driven tilt (TiltCard) — the float never fights
                the tilt since the two animate different transform
                sources composited by `.tilt-card` itself. */}
            <div
              className="animate-fade-up-in relative mx-auto hidden h-80 w-full max-w-md lg:block"
              style={{ animationDelay: "320ms" }}
              aria-hidden="true"
            >
              <TiltCard className="animate-hero-float-a absolute left-0 top-2 w-52 rounded-xl border border-border/60 bg-card p-3 shadow-[var(--shadow-lg)]">
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <FileText className="h-3.5 w-3.5 text-brand-indigo" />
                  Course-Notes.pdf
                </div>
                <div className="space-y-1.5">
                  <div className="h-2 w-full rounded-full bg-muted" />
                  <div className="h-2 w-4/5 rounded-full bg-muted" />
                  <div className="h-2 w-3/5 rounded-full bg-muted" />
                </div>
              </TiltCard>

              <TiltCard className="animate-hero-float-c absolute right-4 top-0 w-40 rounded-xl border border-border/60 bg-card p-3 shadow-[var(--shadow-lg)]">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <PlayCircle className="h-3.5 w-3.5 text-brand-indigo" />
                  Lecture 12
                </div>
                <div className="flex h-12 items-center justify-center rounded-md bg-muted">
                  <Video className="h-4 w-4 text-muted-foreground" />
                </div>
              </TiltCard>

              <TiltCard className="animate-hero-float-b glass-panel absolute bottom-2 right-0 w-64 rounded-xl p-3 shadow-[var(--shadow-lg)]">
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <MessageSquare className="h-3.5 w-3.5 text-brand-indigo" />
                  Your answer
                </div>
                <p className="text-xs leading-relaxed text-foreground">
                  Normalization reduces redundancy by organizing data into related tables…
                </p>
                <span className="mt-2 inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[0.65rem] font-medium text-brand-indigo underline underline-offset-2">
                  Course-Notes.pdf · Page 4
                </span>
              </TiltCard>

              <TiltCard className="animate-hero-float-a absolute bottom-24 left-4 w-44 rounded-lg border border-brand-cyan/30 bg-card px-2.5 py-2 shadow-[var(--shadow-md)]" maxTilt={4}>
                <span className="inline-flex items-center gap-1.5 text-[0.65rem] font-medium text-brand-cyan">
                  <PlayCircle className="h-3 w-3" />
                  Lecture 12 · 12:42
                </span>
              </TiltCard>

              <div className="absolute left-16 top-1/2 h-44 w-44 -translate-y-1/2 rounded-full bg-primary/15 blur-3xl" />
            </div>
          </Spotlight>
        </section>

        {/* Features */}
        <section className="border-b bg-muted/30 py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
            <div className="mx-auto mb-10 max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Everything in one workspace
              </h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {FEATURES.map((feature) => (
                <Card
                  key={feature.title}
                  className="transition-shadow duration-[var(--duration-sm)] hover:shadow-[var(--shadow-md)]"
                >
                  <CardHeader>
                    <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                      <feature.icon className="h-5 w-5 text-brand-indigo" aria-hidden="true" />
                    </div>
                    <CardTitle className="text-base">{feature.title}</CardTitle>
                    <CardDescription>{feature.description}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="border-b py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
            <div className="mx-auto mb-10 max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                How it works
              </h2>
            </div>
            <ol className="grid gap-8 sm:grid-cols-3">
              {STEPS.map((step) => (
                <li key={step.number} className="flex flex-col items-center gap-3 text-center">
                  <span
                    className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground"
                    aria-hidden="true"
                  >
                    {step.number}
                  </span>
                  <h3 className="font-medium">{step.title}</h3>
                  <p className="max-w-[22rem] text-sm text-muted-foreground">
                    {step.description}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Trust */}
        <section className="border-b bg-muted/30 py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
            <div className="mx-auto mb-10 max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Built on trust, not guesswork
              </h2>
            </div>
            <div className="grid gap-6 sm:grid-cols-3">
              {TRUST_POINTS.map((point) => (
                <div key={point.title} className="flex flex-col items-center gap-2 text-center">
                  <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-primary/10">
                    <point.icon className="h-5 w-5 text-brand-indigo" aria-hidden="true" />
                  </div>
                  <h3 className="font-medium">{point.title}</h3>
                  <p className="max-w-[20rem] text-sm text-muted-foreground">{point.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Final CTA */}
        {!session?.user ? (
          <section className="py-16 sm:py-20">
            <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-4 px-4 text-center sm:px-6">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Ready to learn smarter?
              </h2>
              <p className="max-w-md text-muted-foreground">
                Create a free workspace and start asking questions about your own course material.
              </p>
              <Button asChild size="lg">
                <Link href="/signup">
                  Create your free workspace
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </div>
          </section>
        ) : null}
      </main>

      <footer className="border-t py-8">
        <div className="mx-auto flex w-full max-w-5xl flex-col items-center gap-2 px-4 text-center text-sm text-muted-foreground sm:px-6">
          <p className="font-medium text-foreground">Educational Intelligence Copilot</p>
          <p>Learn from your own course material — PDFs, lecture videos, and YouTube links.</p>
        </div>
      </footer>
    </div>
  );
}
