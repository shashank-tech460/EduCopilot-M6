import type { SourceAttribution } from "@/store/appStore";

/**
 * Workspace isolation utility (Accion Labs design, "Workspace Isolation"
 * section, item 3: a workspaceFilter utility that strips/handles
 * references to resources outside the active workspace).
 *
 * Adapted from the design document's conceptual sample to the actual
 * `SourceAttribution` type already defined in store/appStore.ts (Task 1.1)
 * — not a duplicate type. `SourceAttribution.fileId` already matches the
 * spec sample's `attr.fileId` field exactly.
 *
 * This does NOT replace server-side authorization. The server
 * (assertOwnership, per-route ownership checks) remains the actual
 * security boundary — this utility is a defense-in-depth UI-layer safety
 * net: if a response ever contained a citation referencing a file the
 * active workspace doesn't recognize (e.g. a bug elsewhere, or a citation
 * for a file that was since deleted), the UI disables that citation
 * instead of silently trusting it or crashing.
 */
export function filterWorkspaceReferences(
  attributions: SourceAttribution[],
  workspaceFileIds: string[]
): SourceAttribution[] {
  return attributions.map((attribution) => ({
    ...attribution,
    disabled: attribution.disabled || !workspaceFileIds.includes(attribution.fileId),
  }));
}
