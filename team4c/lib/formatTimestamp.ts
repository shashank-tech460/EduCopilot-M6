/**
 * Formats a duration in seconds as m:ss, or h:mm:ss once it reaches an
 * hour. Used by Source Attribution (Requirement 3.1) to display a video
 * timestamp reference, e.g. "2:35" or "1:01:05".
 *
 * No existing formatter was found anywhere in the repository (searched
 * before creating this) — this is the smallest one needed.
 */
export function formatTimestamp(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
