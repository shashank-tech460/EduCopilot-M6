import mongoose, { type Mongoose } from "mongoose";

/**
 * Cached-connection singleton for MongoDB Atlas via Mongoose.
 *
 * Why this exists: in Next.js's dev server (hot reload) and serverless/edge
 * runtimes, a naive `mongoose.connect()` call inside a route handler creates
 * a brand new connection on every invocation/reload. MongoDB Atlas' free
 * tier has a small connection limit, so without caching the app exhausts it
 * within a handful of requests. This module ensures at most one connection
 * (and one in-flight connection attempt) exists for the lifetime of the
 * process, and reuses it across every call to `connectToDatabase()`.
 *
 * Usage (in a Route Handler or server-only module):
 *   import { connectToDatabase } from "@/lib/mongodb";
 *   await connectToDatabase();
 *
 * NOTE: MONGODB_URI is deliberately read *inside* connectToDatabase(), not
 * captured once at module load time. Reading it at module scope meant the
 * value was locked in whenever this file was first imported (e.g. by
 * whatever code path happened to load first during dev-server startup or a
 * test run) — if the environment wasn't fully loaded at that exact moment,
 * every later call saw `undefined` regardless of what .env.local actually
 * contained. Reading it fresh inside the function avoids that entirely.
 */

interface MongooseCache {
  conn: Mongoose | null;
  promise: Promise<Mongoose> | null;
}

// Next.js's dev server hot-reloads modules, which would otherwise reset this
// cache on every file change. Stashing it on `globalThis` survives reloads.
declare global {
  var _mongooseCache: MongooseCache | undefined;
}

const cache: MongooseCache = global._mongooseCache ?? { conn: null, promise: null };
global._mongooseCache = cache;

export async function connectToDatabase(): Promise<Mongoose> {
  if (cache.conn) {
    return cache.conn;
  }

  const MONGODB_URI = process.env.MONGODB_URI;

  if (!MONGODB_URI) {
    throw new Error(
      "MONGODB_URI is not set. Copy .env.example to .env.local and provide a MongoDB Atlas connection string."
    );
  }

  if (!cache.promise) {
    cache.promise = mongoose
      .connect(MONGODB_URI, {
        bufferCommands: false,
        // Fails fast (a few seconds) instead of hanging for the driver's
        // default server-selection timeout (~30s) when Mongo is
        // unreachable — this exact default-timeout behavior is what made a
        // misconfigured/unreachable connection look like a hang rather
        // than a clear, timely error, both in real usage and in tests that
        // accidentally exercise this path against a real-but-unreachable URI.
        serverSelectionTimeoutMS: 5000,
      })
      .catch((error: unknown) => {
        // Reset the in-flight promise on failure so the next call retries
        // instead of permanently caching a rejected connection attempt.
        cache.promise = null;
        throw error instanceof Error
          ? new Error(`Failed to connect to MongoDB: ${error.message}`)
          : error;
      });
  }

  cache.conn = await cache.promise;
  return cache.conn;
}
