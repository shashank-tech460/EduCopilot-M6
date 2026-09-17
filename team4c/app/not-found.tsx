import Link from "next/link";
import { FileQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Also what renders for "workspace exists but isn't yours" (docs/decisions.md
 * §3 — deliberately indistinguishable from "doesn't exist at all"), not
 * just genuinely missing routes.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-full flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-sm text-center">
        <CardHeader className="items-center">
          <FileQuestion className="mb-2 h-10 w-10 text-muted-foreground" />
          <CardTitle>Page not found</CardTitle>
          <CardDescription>
            This page doesn&apos;t exist, or you don&apos;t have access to it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link href="/">Back to home</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
