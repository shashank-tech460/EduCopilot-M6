"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * React Query provider for server-state (workspace data, file lists, chat
 * history — per the Accion Labs architecture's "React Query (Server State)"
 * layer, separate from Zustand's client/application state in appStore.ts).
 *
 * The QueryClient is created once via useState's lazy initializer (not at
 * module scope) so each browser session gets its own client and server-
 * rendered requests don't share a client across users — the standard
 * Next.js App Router pattern for this provider.
 */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
