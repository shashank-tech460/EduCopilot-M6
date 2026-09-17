/**
 * Layout for the (auth) route group.
 * Real Auth.js wiring happens in Phase 4 — this only establishes the route
 * group structure approved in Phase 1.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 items-center justify-center px-4 py-16">
      {children}
    </div>
  );
}
