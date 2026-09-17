import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";

/**
 * Route protection for Team C's authenticated pages.
 *
 * Named `proxy.ts`, not `middleware.ts` — this Next.js version (16)
 * deprecated and renamed the `middleware.js` file convention to `proxy.js`;
 * the behavior is otherwise identical. See:
 * node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md
 *
 * Protects /dashboard and /workspace/* per the Phase 4 spec. Everything
 * else (/, /login, /signup, /api/auth/*) stays public — enforced by the
 * matcher below, not by logic inside the function.
 */
export default auth((req) => {
  const isLoggedIn = !!req.auth;

  if (!isLoggedIn) {
    const loginUrl = new URL("/login", req.nextUrl.origin);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/dashboard/:path*", "/workspace/:path*"],
};
