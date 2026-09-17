import { create } from "zustand";
import { persist, subscribeWithSelector } from "zustand/middleware";

/**
 * App_Store — global application state, per the Accion Labs
 * s4c-application-state-chat-ui design document ("App_Store" section).
 *
 * This is Step 1 of the Accion Labs implementation plan: the store itself,
 * shaped exactly as specified, with all 6 required domains. The
 * components that will actually populate/consume most of these domains
 * (Chat_Panel, Video_Player, File_Manager, workspace initialization) are
 * later steps — this file intentionally does not import or depend on any
 * of them.
 *
 * Technology note (per the approved technology audit): this uses Zustand's
 * `persist` and `subscribeWithSelector` middleware exactly as the spec's
 * own code sample shows, not a hand-rolled alternative.
 */

// ---------------------------------------------------------------------------
// Domain types — shapes taken directly from the Accion Labs document's
// Chat_Panel / Video_Player / File_Manager sections, since the App_Store's
// domains reference them. The *components* that produce/consume these are
// out of scope for Step 1; only the store needs the shapes to compile.
// ---------------------------------------------------------------------------

export interface SourceAttribution {
  type: "video_timestamp" | "pdf_page";
  sourceFile: string;
  fileId: string;
  /** Seconds for a video timestamp, page number for a PDF. */
  location: number;
  label: string;
  disabled?: boolean;
  /**
   * Added for Accion Labs Requirement 3.3 (PDF page navigation). Not part
   * of the original Task 1.1 shape — a citation alone (fileId/type/
   * location) has nothing to actually navigate to; the file's real URL is
   * required to open it. Optional because a disabled/unavailable
   * attribution (Requirement 3.5) may have no resolvable URL at all.
   */
  fileUrl?: string;
  /**
   * Phase 2E correction: additional fields from Team 4B's real
   * `SourceAttribution` contract (chunk_id, relevance_score,
   * section_heading), preserved through the 4C adapter
   * (app/api/chat/route.ts's `toSourceAttribution`) for future UI use --
   * optional and additive, so every existing consumer of this type that
   * only reads the original five fields is completely unaffected.
   */
  chunkId?: string;
  relevanceScore?: number;
  sectionHeading?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attributions?: SourceAttribution[];
  timestamp: Date;
  status: "sending" | "streaming" | "complete" | "error";
}

export interface VideoPlayerState {
  currentTimestamp: number;
  isPlaying: boolean;
  activeMediaId: string | null;
  duration: number;
}

export interface UploadState {
  id: string;
  fileName: string;
  fileType: "pdf" | "mp4" | "youtube";
  fileSize: number;
  uploadDate: Date;
  /** 0-100 */
  progress: number;
  estimatedTimeRemaining: number | null;
  status: "uploading" | "queued" | "processing" | "complete" | "failed" | "ready";
  /** Preserved for retry on failure. */
  fileRef: File | null;
  error?: string;
}

/**
 * Mirrors the identity fields actually available from Auth.js's session
 * (`session.user.id`) — deliberately does NOT include a `token` field.
 * Auth.js's JWT session strategy (lib/auth.ts) never exposes a raw bearer
 * token to client-side code by design (the session lives in an httpOnly
 * cookie); a `token` field here would misrepresent what's actually
 * available and risk someone populating it with something sensitive later.
 */
export interface SessionState {
  userId: string;
}

export interface WorkspaceState {
  id: string;
  name: string;
}

/**
 * A chat message queued locally because the Query_API was unreachable at
 * send time — Accion Labs Requirement 8.1/8.2, Property 17 (FIFO ordering
 * on reconnect). Intentionally minimal: no userId (the server derives the
 * authenticated user from the session on replay, same as any other
 * request — never trust a stored identity), no auth/token material.
 * `videoTimestamp` is preserved for fidelity to what the user actually saw
 * when they asked, even though replay re-reads live state by default (see
 * components/chat/OfflineQueue.ts for the exact replay behavior).
 */
export interface QueuedChatMessage {
  id: string;
  text: string;
  workspaceId: string;
  conversationId: string;
  videoTimestamp: number | null;
  queuedAt: Date;
}

export interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  offlineQueue: QueuedChatMessage[];
  /**
   * MVP M5 correction: the Conversation currently active for THIS
   * ChatPanel session -- server-established only (via
   * hooks/useActiveConversation.ts calling
   * POST /api/workspaces/[id]/conversations), never invented client-side,
   * never derived from workspaceId/userId/title/timestamp/a counter.
   * `activeConversationWorkspaceId` records which workspace the current
   * `activeConversationId` belongs to, so a workspace switch is detected
   * and a NEW conversation is established rather than reusing a stale
   * one from a different workspace -- the conversation otherwise remains
   * stable across re-renders/streamed messages within the same workspace,
   * per this correction's explicit stability requirement.
   */
  activeConversationId: string | null;
  activeConversationWorkspaceId: string | null;
  /**
   * MVP M6 — a NON-AUTHORITATIVE mirror of the server-persisted
   * conversation source scope, for responsive UI only.
   * `null` = "using all workspace materials" (workspace-wide).
   * A non-null array = the document_ids currently believed selected.
   * The actual authoritative value lives in
   * `Conversation.sourceScopeDocumentIds` (Mongo) and is re-resolved
   * server-side on every chat request (lib/sourceScope.ts) --
   * this field is refreshed from the server's own response whenever
   * the selection changes (hooks/useSourceScope.ts), never trusted on
   * its own for anything security-relevant.
   */
  sourceScopeDocumentIds: string[] | null;
}

export interface UiState {
  activePanel: "chat" | "video" | "files";
  sidebarOpen: boolean;
}

// ---------------------------------------------------------------------------
// Store shape
// ---------------------------------------------------------------------------

interface AppState {
  session: SessionState | null;
  workspace: WorkspaceState | null;
  chat: ChatState;
  video: VideoPlayerState;
  uploads: Record<string, UploadState>;
  ui: UiState;

  // Session
  setSession: (session: SessionState | null) => void;
  clearSession: () => void;

  // Workspace
  setWorkspace: (workspace: WorkspaceState | null) => void;
  clearWorkspace: () => void;

  // Chat — signatures match the Accion Labs Chat_Panel streaming sample
  // (`useAppStore.getState().addMessage(message)` /
  // `useAppStore.getState().setMessageError(err.message)`) so later steps
  // can call them without redefining the store.
  addMessage: (message: ChatMessage) => void;
  setMessages: (messages: ChatMessage[]) => void;
  clearMessages: () => void;
  setMessageError: (errorMessage: string) => void;
  setStreaming: (isStreaming: boolean) => void;

  // Offline Queue — Requirement 8.1/8.2. `enqueue` adds to the end,
  // `dequeue` removes by id (called after a successful replay, never to
  // skip a failed one out of order — see components/chat/OfflineQueue.ts).
  enqueueOfflineMessage: (message: QueuedChatMessage) => void;
  dequeueOfflineMessage: (id: string) => void;
  clearOfflineQueue: () => void;

  // Active Conversation (MVP M5 correction) — server-established only;
  // see hooks/useActiveConversation.ts, the only caller of this setter.
  setActiveConversation: (conversationId: string, workspaceId: string) => void;
  clearActiveConversation: () => void;

  // Source scope (MVP M6) -- see ChatState.sourceScopeDocumentIds's own doc comment.
  setSourceScopeDocumentIds: (documentIds: string[] | null) => void;

  // Video — `setVideoTimestamp` signature matches the Accion Labs
  // Video_Player seek-handler sample.
  setVideoTimestamp: (timestamp: number) => void;
  setVideoPlaying: (isPlaying: boolean) => void;
  setActiveMedia: (mediaId: string | null) => void;
  setVideoDuration: (duration: number) => void;

  // Uploads — keyed by upload id.
  addUpload: (id: string, upload: UploadState) => void;
  updateUpload: (id: string, patch: Partial<UploadState>) => void;
  removeUpload: (id: string) => void;
  clearUploads: () => void;

  // UI
  setActivePanel: (panel: UiState["activePanel"]) => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;

  /**
   * Clears all in-memory and persisted session-scoped state, per the
   * Accion Labs Workspace Isolation section ("Cleanup: Logout action
   * clears all in-memory and persisted state") and the document's own
   * `logout` code sample. Deliberately does not reset `ui` — the sample
   * doesn't either, since panel/sidebar layout preference isn't
   * session-scoped data.
   *
   * Persisted localStorage clearing is not a separate step: Zustand's
   * `persist` middleware re-runs `partialize` and re-writes storage after
   * every `set()` call, including this one. Since `workspace` (part of
   * `partialize`) is set to `null` here, the persisted copy in
   * localStorage is overwritten with `null` in the same call — there is
   * no separate "also clear localStorage" step to forget. Verified in
   * tests/unit/appStore.test.ts by reading raw localStorage after calling
   * logout(), not just asserting in-memory state.
   */
  logout: () => void;
}

const initialVideoState: VideoPlayerState = {
  currentTimestamp: 0,
  isPlaying: false,
  activeMediaId: null,
  duration: 0,
};

export const useAppStore = create<AppState>()(
  subscribeWithSelector(
    persist(
      (set) => ({
        session: null,
        workspace: null,
        chat: { messages: [], isStreaming: false, offlineQueue: [], activeConversationId: null, activeConversationWorkspaceId: null, sourceScopeDocumentIds: null },
        video: initialVideoState,
        uploads: {},
        ui: { activePanel: "chat", sidebarOpen: true },

        setSession: (session) => set({ session }),
        clearSession: () => set({ session: null }),

        setWorkspace: (workspace) => set({ workspace }),
        clearWorkspace: () => set({ workspace: null }),

        addMessage: (message) =>
          set((state) => ({
            chat: { ...state.chat, messages: [...state.chat.messages, message] },
          })),
        setMessages: (messages) =>
          set((state) => ({ chat: { ...state.chat, messages } })),
        clearMessages: () =>
          set((state) => ({ chat: { ...state.chat, messages: [] } })),
        setMessageError: (errorMessage) =>
          set((state) => {
            const messages = state.chat.messages;
            const lastMessage = messages[messages.length - 1];
            if (!lastMessage) {
              return state;
            }
            return {
              chat: {
                ...state.chat,
                isStreaming: false,
                messages: [
                  ...messages.slice(0, -1),
                  { ...lastMessage, status: "error", content: errorMessage },
                ],
              },
            };
          }),
        setStreaming: (isStreaming) =>
          set((state) => ({ chat: { ...state.chat, isStreaming } })),

        enqueueOfflineMessage: (message) =>
          set((state) => ({
            chat: { ...state.chat, offlineQueue: [...state.chat.offlineQueue, message] },
          })),
        dequeueOfflineMessage: (id) =>
          set((state) => ({
            chat: {
              ...state.chat,
              offlineQueue: state.chat.offlineQueue.filter((item) => item.id !== id),
            },
          })),
        clearOfflineQueue: () =>
          set((state) => ({ chat: { ...state.chat, offlineQueue: [] } })),

        setActiveConversation: (conversationId, workspaceId) =>
          set((state) => ({
            chat: { ...state.chat, activeConversationId: conversationId, activeConversationWorkspaceId: workspaceId },
          })),
        clearActiveConversation: () =>
          set((state) => ({
            chat: { ...state.chat, activeConversationId: null, activeConversationWorkspaceId: null },
          })),

        setSourceScopeDocumentIds: (documentIds) =>
          set((state) => ({ chat: { ...state.chat, sourceScopeDocumentIds: documentIds } })),

        setVideoTimestamp: (timestamp) =>
          set((state) => ({ video: { ...state.video, currentTimestamp: timestamp } })),
        setVideoPlaying: (isPlaying) =>
          set((state) => ({ video: { ...state.video, isPlaying } })),
        setActiveMedia: (mediaId) =>
          set((state) => ({ video: { ...state.video, activeMediaId: mediaId } })),
        setVideoDuration: (duration) =>
          set((state) => ({ video: { ...state.video, duration } })),

        addUpload: (id, upload) =>
          set((state) => ({ uploads: { ...state.uploads, [id]: upload } })),
        updateUpload: (id, patch) =>
          set((state) => {
            const existing = state.uploads[id];
            if (!existing) {
              return state;
            }
            return {
              uploads: { ...state.uploads, [id]: { ...existing, ...patch } },
            };
          }),
        removeUpload: (id) =>
          set((state) => {
            const rest = { ...state.uploads };
            delete rest[id];
            return { uploads: rest };
          }),
        clearUploads: () => set({ uploads: {} }),

        setActivePanel: (activePanel) =>
          set((state) => ({ ui: { ...state.ui, activePanel } })),
        setSidebarOpen: (sidebarOpen) =>
          set((state) => ({ ui: { ...state.ui, sidebarOpen } })),
        toggleSidebar: () =>
          set((state) => ({ ui: { ...state.ui, sidebarOpen: !state.ui.sidebarOpen } })),

        logout: () =>
          set({
            session: null,
            workspace: null,
            chat: { messages: [], isStreaming: false, offlineQueue: [], activeConversationId: null, activeConversationWorkspaceId: null, sourceScopeDocumentIds: null },
            video: initialVideoState,
            uploads: {},
          }),
      }),
      {
        name: "app-store",
        // Only "critical state" persists, per Accion Labs Property 14
        // ("workspace identifier, UI layout preferences, video timestamp,
        // active media") — session, full chat history, and in-flight
        // uploads are deliberately excluded, matching the document's own
        // `partialize` sample exactly.
        partialize: (state) => ({
          workspace: state.workspace,
          ui: state.ui,
          video: {
            currentTimestamp: state.video.currentTimestamp,
            activeMediaId: state.video.activeMediaId,
          },
        }),
      }
    )
  )
);
