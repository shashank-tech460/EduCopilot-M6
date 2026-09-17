import type { DefaultSession } from "next-auth";

/**
 * Augments Auth.js's default types so `session.user.id` and `token.id` are
 * recognized by TypeScript. Auth.js's default Session/JWT shapes don't
 * include `id` — our authorize()/jwt()/session() callbacks in lib/auth.ts
 * add it, so the types need to reflect that.
 */
declare module "next-auth" {
  interface Session {
    user: {
      id: string;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id?: string;
  }
}
