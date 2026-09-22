import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

import { AuthSessionProvider } from "@/components/shared/auth-session-provider";
import { QueryProvider } from "@/components/shared/query-provider";
import { Toaster } from "@/components/shared/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";

// Self-hosted via next/font (no runtime request to Google Fonts, no
// render-blocking <link>, no layout shift) — the one new dependency this
// visual pass introduces, justified by the "high-quality typography"
// requirement; every other page continues using the existing shadcn/
// Tailwind primitives.
const inter = Inter({ subsets: ["latin"], variable: "--font-sans-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Educational Intelligence Copilot",
  description:
    "Ask questions about your own lecture videos and course material, and jump straight to the moment a concept is explained.",
};

/**
 * Phase 6H — the app now defaults to the dark, premium theme (`className="dark"`).
 * This is a deliberate product decision, not a user preference toggle:
 * the existing `.dark` custom-variant mechanism (app/globals.css) already
 * supported this exact switch — only the class placement changed. No
 * component was rewritten to support dark mode; every existing page
 * already used the semantic `bg-background`/`text-foreground`/etc. tokens
 * this class controls.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark h-full antialiased ${inter.variable}`}>
      <body className="min-h-full flex flex-col font-sans">
        <AuthSessionProvider>
          <QueryProvider>
            <TooltipProvider delayDuration={200}>
              {children}
              <Toaster />
            </TooltipProvider>
          </QueryProvider>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
