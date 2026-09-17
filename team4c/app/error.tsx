"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * App Router's error boundary convention — must be a Client Component.
 * Catches unexpected runtime errors in this segment so a student sees a
 * recoverable screen instead of a blank page or a raw stack trace.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Server-side error logging only (per docs/decisions.md §12's
    // "basic logging" note) — never render error.message to the page,
    // since server errors can carry details (e.g. a DB error string) that
    // shouldn't reach the browser.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-full flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-sm text-center">
        <CardHeader className="items-center">
          <AlertTriangle className="mb-2 h-10 w-10 text-destructive" />
          <CardTitle>Something went wrong</CardTitle>
          <CardDescription>
            An unexpected error occurred. You can try again.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={reset}>Try again</Button>
        </CardContent>
      </Card>
    </div>
  );
}
