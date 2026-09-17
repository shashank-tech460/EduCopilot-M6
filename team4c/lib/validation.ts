const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const MIN_PASSWORD_LENGTH = 8;

export interface SignupInput {
  name: string;
  email: string;
  password: string;
  confirmPassword: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: Partial<Record<keyof SignupInput, string>>;
}

/**
 * Pure validation logic for the signup form, deliberately separated from
 * the API route so it can be unit tested without a database connection or
 * bcrypt (per the Phase 4 testing requirements — "signup validation" is
 * listed as its own test target, distinct from "duplicate email handling",
 * which does need the database).
 */
export function validateSignupInput(input: Partial<SignupInput>): ValidationResult {
  const errors: ValidationResult["errors"] = {};

  const name = input.name?.trim() ?? "";
  const email = input.email?.trim() ?? "";
  const password = input.password ?? "";
  const confirmPassword = input.confirmPassword ?? "";

  if (!name) {
    errors.name = "Name is required.";
  }

  if (!email) {
    errors.email = "Email is required.";
  } else if (!EMAIL_REGEX.test(email)) {
    errors.email = "Enter a valid email address.";
  }

  if (!password) {
    errors.password = "Password is required.";
  } else if (password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }

  if (!confirmPassword) {
    errors.confirmPassword = "Please confirm your password.";
  } else if (password && confirmPassword !== password) {
    errors.confirmPassword = "Passwords do not match.";
  }

  return { valid: Object.keys(errors).length === 0, errors };
}

export const MAX_WORKSPACE_NAME_LENGTH = 60;

export interface WorkspaceNameValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * Pure validation for workspace names, deliberately separated from the API
 * route (same reasoning as validateSignupInput above) so it's independently
 * unit-testable without a database connection.
 */
export function validateWorkspaceName(name: unknown): WorkspaceNameValidationResult {
  if (typeof name !== "string") {
    return { valid: false, error: "Workspace name is required." };
  }

  const trimmed = name.trim();

  if (!trimmed) {
    return { valid: false, error: "Workspace name is required." };
  }

  if (trimmed.length > MAX_WORKSPACE_NAME_LENGTH) {
    return {
      valid: false,
      error: `Workspace name must be ${MAX_WORKSPACE_NAME_LENGTH} characters or fewer.`,
    };
  }

  return { valid: true };
}

export interface SimpleValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * Matches the two common YouTube URL forms named in the Phase 6 spec:
 *   https://www.youtube.com/watch?v=VIDEO_ID  (also without "www.")
 *   https://youtu.be/VIDEO_ID
 * Deliberately does NOT accept arbitrary URLs, YouTube playlist/channel
 * URLs, or bare video IDs — only a URL that is recognizably one of these
 * two shapes, so nothing that isn't actually a playable single video slips
 * through as "youtube_url" material.
 */
const YOUTUBE_URL_REGEX =
  /^https?:\/\/(www\.)?(youtube\.com\/watch\?(?:.*&)?v=[\w-]{6,}|youtu\.be\/[\w-]{6,})([?&].*)?$/i;

export function validateYoutubeUrl(url: unknown): SimpleValidationResult {
  if (typeof url !== "string" || !url.trim()) {
    return { valid: false, error: "A YouTube URL is required." };
  }

  if (!YOUTUBE_URL_REGEX.test(url.trim())) {
    return {
      valid: false,
      error: "Enter a valid YouTube URL (e.g. youtube.com/watch?v=... or youtu.be/...).",
    };
  }

  return { valid: true };
}

// Accion Labs Requirement 5.1/5.4: PDF <= 50MB, MP4 <= 500MB. These replace
// the earlier dev-safe placeholders (20MB/200MB) — this is now the actual
// product limit, not a temporary cap.
//
// Note: this constant governs client/server *validation* only. It does not
// by itself guarantee a 500MB upload succeeds in every deployment
// environment — Next.js Route Handlers (unlike Server Actions) have no
// body-size config in this project's next.config.ts, so nothing in this
// codebase blocks it locally or on a self-hosted Node server. Serverless
// hosting platforms (e.g. Vercel) impose their own separate request-body
// ceiling on functions, which this validation constant cannot override —
// a genuinely large-file-tolerant production deployment would need a
// direct-to-object-storage (presigned URL) upload path instead of routing
// bytes through this API route. That's a deployment/infrastructure
// decision outside Task 6.1's scope, flagged here rather than silently
// assumed away.
export const MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024; // 50MB
export const MAX_VIDEO_SIZE_BYTES = 500 * 1024 * 1024; // 500MB

export interface UploadableFileLike {
  name: string;
  type: string;
  size: number;
}

function isUploadableFileLike(value: unknown): value is UploadableFileLike {
  return (
    typeof value === "object" &&
    value !== null &&
    "name" in value &&
    "type" in value &&
    "size" in value
  );
}

/**
 * Validates a PDF or MP4 upload by MIME type (primary check) with a
 * filename-extension fallback, since browsers/OSes don't always report a
 * MIME type for every file. Accepts a plain `{name, type, size}` shape
 * rather than requiring a real File/Blob instance, so this is testable with
 * plain objects and doesn't need jsdom's File polyfill.
 */
export function validateUploadedFile(
  file: unknown,
  materialType: "pdf" | "video"
): SimpleValidationResult {
  if (!isUploadableFileLike(file)) {
    return { valid: false, error: "A file is required." };
  }

  const { name, type, size } = file;
  const lowerName = name.toLowerCase();

  if (materialType === "pdf") {
    const isPdf = type === "application/pdf" || lowerName.endsWith(".pdf");
    if (!isPdf) {
      return { valid: false, error: "Only PDF files are accepted." };
    }
    if (size > MAX_PDF_SIZE_BYTES) {
      return {
        valid: false,
        error: `PDF must be ${MAX_PDF_SIZE_BYTES / (1024 * 1024)}MB or smaller.`,
      };
    }
    return { valid: true };
  }

  const isMp4 = type === "video/mp4" || lowerName.endsWith(".mp4");
  if (!isMp4) {
    return { valid: false, error: "Only MP4 video files are accepted." };
  }
  if (size > MAX_VIDEO_SIZE_BYTES) {
    return {
      valid: false,
      error: `Video must be ${MAX_VIDEO_SIZE_BYTES / (1024 * 1024)}MB or smaller.`,
    };
  }
  return { valid: true };
}
