import Link from "next/link";
import {
  ArrowRight,
  FolderKanban,
  MessageSquare,
  Upload,
  Video,
} from "lucide-react";

import { SiteNav } from "@/components/shared/site-nav";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

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

import { auth } from "@/lib/auth";

export default async function Home() {
  const session = await auth();

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <SiteNav />

      <main className="flex-1">
        {/* Hero */}
        <section className="mx-auto flex w-full max-w-5xl flex-col items-center gap-6 px-4 py-20 text-center sm:px-6 sm:py-28">
          <h1 className="max-w-2xl text-4xl font-semibold tracking-tight sm:text-5xl">
            Learn from your own course material.
          </h1>
          <p className="max-w-xl text-balance text-lg text-muted-foreground">
            Upload PDFs, lecture videos, and YouTube links into one workspace.
            Ask questions about your material and get answers grounded in
            what you&apos;ve actually studied.
          </p>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            {session?.user ? (
              <Button asChild size="lg">
                <Link href="/dashboard">
                  Open Dashboard
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild size="lg">
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
        </section>

        {/* Features */}
        <section className="border-t bg-muted/30 py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
            <div className="mx-auto mb-10 max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Everything in one workspace
              </h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {FEATURES.map((feature) => (
                <Card key={feature.title}>
                  <CardHeader>
                    <feature.icon className="h-6 w-6 text-primary" aria-hidden="true" />
                    <CardTitle className="text-base">{feature.title}</CardTitle>
                    <CardDescription>{feature.description}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="py-16 sm:py-20">
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
