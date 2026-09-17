/**
 * Transcript provider abstraction (local mock, per this task's explicit
 * request — NOT a real speech-to-text or YouTube-captions integration).
 *
 * Mirrors the existing services/teamA and services/teamB pattern: define
 * the contract once, implement a mock now, leave the door open for a real
 * provider (real STT output, YouTube's caption API, etc.) to implement the
 * exact same interface later without any calling code changing.
 */

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface TranscriptMaterial {
  fileId: string;
  originalName: string;
}

export interface TranscriptProvider {
  getSegments(material: TranscriptMaterial): Promise<TranscriptSegment[]>;
}
