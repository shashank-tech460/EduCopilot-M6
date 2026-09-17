import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcrypt";

import { connectToDatabase } from "@/lib/mongodb";
import { UserModel } from "@/models/User";

/**
 * Auth.js (v5) configuration.
 *
 * Uses the existing `users` collection and `UserModel` from Phase 3 — this
 * is not a second authentication/database system, just the auth layer on
 * top of what already exists (per the Phase 4 instructions).
 *
 * Session strategy is JWT (docs/decisions.md §7): stateless, no separate
 * session collection needed, works cleanly with Next.js server components
 * and middleware.
 */
export const { handlers, auth, signIn, signOut } = NextAuth({
  // Required for Auth.js v5 to accept requests to a host it can't verify
  // automatically (this is exactly what was causing "UntrustedHost: Host
  // must be trusted" on localhost — Auth.js v5 doesn't implicitly trust
  // arbitrary hosts, dev or not, unless told to). Safe for local
  // development and for a single-deployment-target production setup like
  // Vercel; if this app is ever deployed behind multiple/rotating
  // hostnames, revisit this rather than trusting every Host header blindly.
  trustHost: true,
  session: {
    strategy: "jwt",
  },
  pages: {
    signIn: "/login",
  },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email =
          typeof credentials?.email === "string" ? credentials.email.toLowerCase().trim() : "";
        const password = typeof credentials?.password === "string" ? credentials.password : "";

        if (!email || !password) {
          return null;
        }

        await connectToDatabase();

        // passwordHash has `select: false` in the schema, so it must be
        // explicitly requested here — this is the one place in the app
        // that legitimately needs it.
        const user = await UserModel.findOne({ email }).select("+passwordHash");
        if (!user) {
          return null;
        }

        const passwordMatches = await bcrypt.compare(password, user.passwordHash);
        if (!passwordMatches) {
          return null;
        }

        // Never return passwordHash (or anything beyond what's needed) from
        // authorize() — whatever is returned here ends up in the JWT.
        return {
          id: user._id.toString(),
          name: user.name,
          email: user.email,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && typeof token.id === "string") {
        session.user.id = token.id;
      }
      return session;
    },
  },
});
