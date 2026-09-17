import { randomUUID } from "crypto";
import { mkdir, readFile, unlink, writeFile } from "fs/promises";
import path from "path";

import { mintLocalStorageCapabilityToken } from "@/lib/localStorageCapability";

const LOCAL_STORAGE_ROOT = path.join(process.cwd(), ".local-uploads");
export const LOCAL_MOCK_PROVIDER = "local-mock";
export const YOUTUBE_PROVIDER = "youtube";

/**
 * MVP M6 local-stack correction: the local storage mock's own URL must
 * be a FULLY QUALIFIED http(s) URL, not the relative path
 * (`/api/local-storage/...`) this returned before. Team 4A's frozen
 * canonical contract (`CanonicalIngestRequest.file_url`) requires a
 * fully qualified `http://`/`https://` URL, and Team 4A's Phase 2C-R
 * secure remote-source resolver only ever fetches from an explicitly
 * trusted, exact hostname it can actually resolve and connect to — a
 * relative path is neither.
 *
 * Reuses `AUTH_URL` (Auth.js's own "what origin is this app running
 * at" configuration, already present and already correctly defaulted
 * to `http://localhost:3000` for local development in `.env.example`)
 * rather than introducing a second, redundant "public origin" setting
 * -- this is exactly the same concept Auth.js's own `AUTH_URL` already
 * represents, just read here for a second, unrelated purpose. Falls
 * back to the same `http://localhost:3000` default `.env.example`
 * already documents, only if `AUTH_URL` is entirely unset, so this
 * function never silently produces a relative URL again.
 *
 * This does not change PRODUCTION architecture semantics at all: a
 * real deployment sets `STORAGE_PROVIDER` (see `storeFile()` below),
 * which returns a real, already fully-qualified HTTPS object-storage
 * URL from that provider's own SDK -- this function and its use of
 * `AUTH_URL` are reached only by the local development mock path.
 */
function resolveLocalStoragePublicOrigin(): string {
  return process.env.AUTH_URL || "http://localhost:3000";
}

export interface StoredFileReference {
  storageUrl: string;
  storageProvider: string;
  publicId: string;
}

/**
 * Minimal shape this module needs from an uploaded file — matches both the
 * Web platform `File` interface (what `request.formData()` gives us in a
 * Route Handler) and a plain test double, so storage logic is testable
 * without constructing a real File/Blob.
 */
export interface UploadableFile {
  name: string;
  arrayBuffer(): Promise<ArrayBuffer>;
}

/**
 * Object storage abstraction (docs/decisions.md §8/§11: "MongoDB stores
 * metadata; object storage stores the actual PDF/video bytes").
 *
 * No real provider (Cloudinary/UploadThing/S3) is wired up yet — the
 * project's own docs mark the provider choice as pending Team A's file-
 * input contract (docs/api-contracts.md §A). Per the Phase 6 instructions,
 * this is intentional: rather than block file uploads entirely on that
 * unresolved decision, or half-implement one specific provider's SDK, this
 * function provides a working LOCAL DEVELOPMENT MOCK when STORAGE_PROVIDER
 * is unset, and fails loudly (rather than silently no-op'ing) if a provider
 * name is set but not actually wired up — so nobody mistakes a
 * misconfigured deployment for a working one.
 */
export async function storeFile(
  file: UploadableFile,
  workspaceId: string
): Promise<StoredFileReference> {
  const provider = process.env.STORAGE_PROVIDER;

  if (!provider) {
    return storeFileLocally(file, workspaceId);
  }

  throw new Error(
    `STORAGE_PROVIDER="${provider}" is set, but no real object-storage integration is implemented yet (Phase 6 only implements the local development mock). Unset STORAGE_PROVIDER to use it.`
  );
}

/**
 * DEV-ONLY MOCK: writes the file to a git-ignored local folder outside
 * Next.js's `public/` directory (so it isn't bundled into the build), and
 * serves it back via app/api/local-storage/[...path]/route.ts, which
 * enforces the same workspace-ownership check as everywhere else. This is
 * explicitly not production-suitable — a real deployment needs a real
 * `STORAGE_PROVIDER` — but it means uploads actually work end-to-end on a
 * developer's machine with zero external accounts required.
 */
async function storeFileLocally(
  file: UploadableFile,
  workspaceId: string
): Promise<StoredFileReference> {
  const workspaceDir = path.join(LOCAL_STORAGE_ROOT, workspaceId);
  await mkdir(workspaceDir, { recursive: true });

  const publicId = `${randomUUID()}-${sanitizeFilename(file.name)}`;
  const buffer = Buffer.from(await file.arrayBuffer());
  await writeFile(path.join(workspaceDir, publicId), buffer);

  const origin = resolveLocalStoragePublicOrigin();
  // MVP M6 correction (round 2): `storageUrl` is now PLAIN -- no
  // capability token embedded. It is persisted in Mongo and reused
  // FOREVER as the citation link the browser clicks, potentially long
  // after upload; the earlier design embedded a short-lived (10-minute)
  // capability token directly into this same, permanently-stored URL,
  // which meant every citation click after those 10 minutes elapsed
  // carried an EXPIRED token -- and an invalid/expired capability
  // MUST NOT fall back to browser-session authorization (a deliberate,
  // required security property, preserved exactly) -- so citations
  // reliably 404'd. Browser clicks on this plain URL now correctly take
  // the unchanged, existing browser-session/`assertOwnership()` path in
  // app/api/local-storage/[...path]/route.ts, exactly as they did
  // before any capability mechanism existed.
  //
  // The SEPARATE, short-lived capability URL Team 4A's server-to-server
  // resolver actually needs is minted fresh, on demand, by
  // `mintLocalStorageRetrievalUrl()` below -- called only at the moment
  // of constructing the canonical /v1/ingest request body (see
  // app/api/workspaces/[id]/files/route.ts's `handOffToTeamA`), never
  // stored anywhere.
  const storageUrl = `${origin}/api/local-storage/${workspaceId}/${encodeURIComponent(publicId)}`;

  return {
    storageUrl,
    storageProvider: LOCAL_MOCK_PROVIDER,
    publicId,
  };
}

/**
 * MVP M6 correction (round 2) -- mints a FRESH, short-lived capability
 * URL for Team 4A's server-to-server canonical ingestion fetch, given a
 * File's already-persisted `storageUrl`/`storageProvider`/`publicId`.
 *
 * For `LOCAL_MOCK_PROVIDER` files: appends a brand-new
 * `?capability=<token>` (minted right now, valid for the mechanism's own
 * short TTL -- see lib/localStorageCapability.ts) to the plain
 * `storageUrl`. Called exactly once per ingestion attempt (including
 * each re-ingestion attempt, which mints its own fresh token) -- never
 * persisted, so it can never go stale the way embedding it in the
 * stored `storageUrl` did.
 *
 * For any other provider (a real object-storage `storageUrl`, or a
 * YouTube reference): returns `storageUrl` completely unchanged -- a
 * real provider's URL is already its own, independently-authorized
 * (presigned or public) HTTPS URL; this mechanism exists solely for the
 * local development mock.
 */
export async function mintLocalStorageRetrievalUrl(file: {
  storageUrl: string;
  storageProvider?: string | null;
  publicId?: string | null;
  workspaceId: string;
}): Promise<string> {
  if (file.storageProvider !== LOCAL_MOCK_PROVIDER || !file.publicId) {
    return file.storageUrl;
  }

  const token = await mintLocalStorageCapabilityToken(file.workspaceId, file.publicId);
  return `${file.storageUrl}?capability=${encodeURIComponent(token)}`;
}

/**
 * YouTube materials need no storage operation at all — the URL itself is
 * the reference (docs/decisions.md §8: "YouTube URLs → no storage needed").
 */
export function referenceYoutubeUrl(url: string): StoredFileReference {
  return {
    storageUrl: url,
    storageProvider: YOUTUBE_PROVIDER,
    publicId: url,
  };
}

/**
 * Reads a locally-stored file's raw bytes back — used by mock Team B's PDF
 * text extraction (services/teamB/mock.ts). Only ever meaningful for
 * `LOCAL_MOCK_PROVIDER` files; returns null for anything else (a YouTube
 * reference has no bytes to read, and a real provider isn't implemented
 * yet — same "fail safe, don't pretend" posture as the rest of this
 * module) rather than throwing and crashing the chat request.
 */
export async function readStoredFile(
  storageProvider: string | undefined,
  publicId: string | undefined,
  workspaceId: string
): Promise<Buffer | null> {
  if (storageProvider !== LOCAL_MOCK_PROVIDER || !publicId) {
    return null;
  }
  try {
    return await readFile(path.join(LOCAL_STORAGE_ROOT, workspaceId, publicId));
  } catch {
    return null;
  }
}

/**
 * Best-effort deletion. Only actually removes bytes for the local mock
 * provider — a YouTube reference has nothing to delete, and a real
 * provider's deletion would go through its own SDK once implemented.
 * Swallows errors deliberately: a file that's already gone (or a workspace
 * folder that was never created) shouldn't block the MongoDB deletion the
 * caller performs regardless.
 */
export async function deleteStoredFile(
  storageProvider: string | undefined,
  publicId: string | undefined,
  workspaceId: string
): Promise<void> {
  if (storageProvider !== LOCAL_MOCK_PROVIDER || !publicId) {
    return;
  }

  try {
    await unlink(path.join(LOCAL_STORAGE_ROOT, workspaceId, publicId));
  } catch {
    // Already gone, or never existed — not an error worth surfacing.
  }
}

/**
 * Resolves the on-disk path for a stored file, and verifies it actually
 * stays inside that workspace's directory before returning it.
 *
 * Why this matters: `publicId` reaches this function from a URL segment
 * (app/api/local-storage/[...path]/route.ts), decoded via
 * decodeURIComponent(). Without this check, a crafted publicId containing
 * `../` sequences could resolve outside LOCAL_STORAGE_ROOT/workspaceId
 * entirely (e.g. reading another workspace's files, or arbitrary files on
 * disk) — `path.join()` alone normalizes `..` segments rather than
 * rejecting them, so joining is not sufficient protection by itself.
 * Returns null (rather than throwing) so the route can respond with the
 * same safe 404 used for every other "this doesn't exist/isn't yours" case
 * in this project, instead of a distinguishing error.
 */
export function resolveLocalStoragePath(workspaceId: string, publicId: string): string | null {
  const workspaceDir = path.resolve(LOCAL_STORAGE_ROOT, workspaceId);
  const resolved = path.resolve(workspaceDir, publicId);

  const isWithinWorkspaceDir =
    resolved === workspaceDir || resolved.startsWith(workspaceDir + path.sep);

  return isWithinWorkspaceDir ? resolved : null;
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_");
}
