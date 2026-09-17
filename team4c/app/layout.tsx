import type { Metadata } from "next";
import "./globals.css";

import { AuthSessionProvider } from "@/components/shared/auth-session-provider";
import { QueryProvider } from "@/components/shared/query-provider";
import { Toaster } from "@/components/shared/toaster";

export const metadata: Metadata = {
  title: "Educational Intelligence Copilot",
  description:
    "Ask questions about your own lecture videos and course material, and jump straight to the moment a concept is explained.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <AuthSessionProvider>
          <QueryProvider>
            {children}
            <Toaster />
          </QueryProvider>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
