import { describe, expect, it, beforeEach } from "vitest";

import { useAppStore } from "@/store/appStore";

/**
 * Tests the App_Store created in Step 1 against the Accion Labs
 * requirements/properties that apply to the store itself (as opposed to
 * the not-yet-built components that will consume it):
 *
 * - Requirement 7.1–7.2: all 6 domains exist with the specified shape
 * - Requirement 7.3 / Property 14: persist/restore round-trip for critical
 *   state (workspace, ui, video.currentTimestamp + activeMediaId)
 * - Requirement 7.3: session, full chat history, and uploads are NOT
 *   persisted (matches the document's own `partialize` sample)
 * - Workspace Isolation "Cleanup" requirement: logout() clears session,
 *   workspace, chat, video, and uploads
 * - The exact action signatures other Accion Labs components will call
 *   directly (`addMessage`, `setMessageError`, `setVideoTimestamp`),
 *   verified now so Step 3/4 aren't discovering a signature mismatch later
 *
 * No DOM, no DB, no network — this is pure Zustand store logic, run
 * directly in Vitest's Node/jsdom environment.
 */

function resetStore() {
  useAppStore.setState({
    session: null,
    workspace: null,
    chat: { messages: [], isStreaming: false, offlineQueue: [], activeConversationId: null, activeConversationWorkspaceId: null, sourceScopeDocumentIds: null },
    video: { currentTimestamp: 0, isPlaying: false, activeMediaId: null, duration: 0 },
    uploads: {},
    ui: { activePanel: "chat", sidebarOpen: true },
  });
}

beforeEach(() => {
  resetStore();
  localStorage.clear();
});

describe("App_Store — initial shape", () => {
  it("has all 6 required domains with the specified initial values", () => {
    const state = useAppStore.getState();
    expect(state.session).toBeNull();
    expect(state.workspace).toBeNull();
    expect(state.chat).toEqual({ messages: [], isStreaming: false, offlineQueue: [], activeConversationId: null, activeConversationWorkspaceId: null, sourceScopeDocumentIds: null });
    expect(state.video).toEqual({
      currentTimestamp: 0,
      isPlaying: false,
      activeMediaId: null,
      duration: 0,
    });
    expect(state.uploads).toEqual({});
    expect(state.ui).toEqual({ activePanel: "chat", sidebarOpen: true });
  });
});

describe("App_Store — session and workspace", () => {
  it("setSession sets and clears the session", () => {
    useAppStore.getState().setSession({ userId: "user-1" });
    expect(useAppStore.getState().session).toEqual({ userId: "user-1" });

    useAppStore.getState().setSession(null);
    expect(useAppStore.getState().session).toBeNull();
  });

  it("clearSession clears the session directly", () => {
    useAppStore.getState().setSession({ userId: "user-1" });
    useAppStore.getState().clearSession();
    expect(useAppStore.getState().session).toBeNull();
  });

  it("setWorkspace sets the active workspace", () => {
    useAppStore.getState().setWorkspace({ id: "ws-1", name: "DBMS" });
    expect(useAppStore.getState().workspace).toEqual({ id: "ws-1", name: "DBMS" });
  });

  it("clearWorkspace clears the active workspace directly", () => {
    useAppStore.getState().setWorkspace({ id: "ws-1", name: "DBMS" });
    useAppStore.getState().clearWorkspace();
    expect(useAppStore.getState().workspace).toBeNull();
  });
});

describe("App_Store — chat domain", () => {
  it("addMessage appends to the message list (signature matches the Accion Labs useChatStream sample)", () => {
    const message = {
      id: "m1",
      role: "user" as const,
      content: "What is normalization?",
      timestamp: new Date(),
      status: "complete" as const,
    };

    useAppStore.getState().addMessage(message);

    expect(useAppStore.getState().chat.messages).toHaveLength(1);
    expect(useAppStore.getState().chat.messages[0]).toEqual(message);
  });

  it("setMessageError marks the most recent message as errored (signature matches the Accion Labs sample)", () => {
    useAppStore.getState().addMessage({
      id: "m1",
      role: "assistant",
      content: "",
      timestamp: new Date(),
      status: "streaming",
    });

    useAppStore.getState().setMessageError("Stream disconnected.");

    const last = useAppStore.getState().chat.messages.at(-1);
    expect(last?.status).toBe("error");
    expect(last?.content).toBe("Stream disconnected.");
    expect(useAppStore.getState().chat.isStreaming).toBe(false);
  });

  it("setStreaming toggles the streaming flag independently of messages", () => {
    useAppStore.getState().setStreaming(true);
    expect(useAppStore.getState().chat.isStreaming).toBe(true);
    expect(useAppStore.getState().chat.messages).toEqual([]);
  });

  it("setMessages replaces the entire message list at once", () => {
    const messages = [
      { id: "m1", role: "user" as const, content: "a", timestamp: new Date(), status: "complete" as const },
      { id: "m2", role: "assistant" as const, content: "b", timestamp: new Date(), status: "complete" as const },
    ];
    useAppStore.getState().setMessages(messages);
    expect(useAppStore.getState().chat.messages).toEqual(messages);
  });

  it("clearMessages empties the message list without touching isStreaming", () => {
    useAppStore.getState().addMessage({
      id: "m1",
      role: "user",
      content: "hi",
      timestamp: new Date(),
      status: "complete",
    });
    useAppStore.getState().setStreaming(true);

    useAppStore.getState().clearMessages();

    expect(useAppStore.getState().chat.messages).toEqual([]);
    expect(useAppStore.getState().chat.isStreaming).toBe(true);
  });
});

describe("App_Store — video domain", () => {
  it("setVideoTimestamp updates only the timestamp (signature matches the Accion Labs seek-handler sample)", () => {
    useAppStore.getState().setVideoPlaying(true);
    useAppStore.getState().setVideoTimestamp(1935);

    const video = useAppStore.getState().video;
    expect(video.currentTimestamp).toBe(1935);
    expect(video.isPlaying).toBe(true);
  });

  it("setActiveMedia and setVideoDuration update independently", () => {
    useAppStore.getState().setActiveMedia("file-1");
    useAppStore.getState().setVideoDuration(2745);

    const video = useAppStore.getState().video;
    expect(video.activeMediaId).toBe("file-1");
    expect(video.duration).toBe(2745);
  });
});

describe("App_Store — uploads domain", () => {
  it("addUpload, updateUpload, and removeUpload manage the uploads map by id", () => {
    useAppStore.getState().addUpload("u1", {
      id: "u1",
      fileName: "Lecture12.pdf",
      fileType: "pdf",
      fileSize: 1024,
      uploadDate: new Date(),
      progress: 0,
      estimatedTimeRemaining: null,
      status: "uploading",
      fileRef: null,
    });

    useAppStore.getState().updateUpload("u1", { progress: 42, estimatedTimeRemaining: 8 });
    expect(useAppStore.getState().uploads.u1.progress).toBe(42);
    expect(useAppStore.getState().uploads.u1.estimatedTimeRemaining).toBe(8);

    useAppStore.getState().removeUpload("u1");
    expect(useAppStore.getState().uploads.u1).toBeUndefined();
  });

  it("updateUpload on a nonexistent id is a safe no-op", () => {
    useAppStore.getState().updateUpload("missing", { progress: 50 });
    expect(useAppStore.getState().uploads).toEqual({});
  });

  it("clearUploads removes every upload record at once", () => {
    useAppStore.getState().addUpload("u1", {
      id: "u1",
      fileName: "a.pdf",
      fileType: "pdf",
      fileSize: 10,
      uploadDate: new Date(),
      progress: 10,
      estimatedTimeRemaining: null,
      status: "uploading",
      fileRef: null,
    });
    useAppStore.getState().addUpload("u2", {
      id: "u2",
      fileName: "b.mp4",
      fileType: "mp4",
      fileSize: 20,
      uploadDate: new Date(),
      progress: 20,
      estimatedTimeRemaining: null,
      status: "uploading",
      fileRef: null,
    });

    useAppStore.getState().clearUploads();
    expect(useAppStore.getState().uploads).toEqual({});
  });
});

describe("App_Store — ui domain", () => {
  it("setActivePanel and toggleSidebar update independently of other domains", () => {
    useAppStore.getState().setActivePanel("video");
    expect(useAppStore.getState().ui.activePanel).toBe("video");

    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().ui.sidebarOpen).toBe(false);
  });

  it("setSidebarOpen sets the sidebar state explicitly (not just toggling)", () => {
    useAppStore.getState().setSidebarOpen(false);
    expect(useAppStore.getState().ui.sidebarOpen).toBe(false);

    useAppStore.getState().setSidebarOpen(false);
    expect(useAppStore.getState().ui.sidebarOpen).toBe(false);

    useAppStore.getState().setSidebarOpen(true);
    expect(useAppStore.getState().ui.sidebarOpen).toBe(true);
  });
});

describe("App_Store — logout (Workspace Isolation cleanup requirement)", () => {
  it("clears session, workspace, chat, video, and uploads", () => {
    useAppStore.getState().setSession({ userId: "user-1" });
    useAppStore.getState().setWorkspace({ id: "ws-1", name: "DBMS" });
    useAppStore.getState().addMessage({
      id: "m1",
      role: "user",
      content: "hi",
      timestamp: new Date(),
      status: "complete",
    });
    useAppStore.getState().setVideoTimestamp(500);
    useAppStore.getState().addUpload("u1", {
      id: "u1",
      fileName: "a.pdf",
      fileType: "pdf",
      fileSize: 10,
      uploadDate: new Date(),
      progress: 100,
      estimatedTimeRemaining: 0,
      status: "complete",
      fileRef: null,
    });

    useAppStore.getState().logout();

    const state = useAppStore.getState();
    expect(state.session).toBeNull();
    expect(state.workspace).toBeNull();
    expect(state.chat).toEqual({ messages: [], isStreaming: false, offlineQueue: [], activeConversationId: null, activeConversationWorkspaceId: null, sourceScopeDocumentIds: null });
    expect(state.video).toEqual({
      currentTimestamp: 0,
      isPlaying: false,
      activeMediaId: null,
      duration: 0,
    });
    expect(state.uploads).toEqual({});
  });

  it("does not reset ui, matching the Accion Labs logout sample", () => {
    useAppStore.getState().setActivePanel("files");
    useAppStore.getState().toggleSidebar();

    useAppStore.getState().logout();

    expect(useAppStore.getState().ui).toEqual({ activePanel: "files", sidebarOpen: false });
  });

  it("clears the PERSISTED localStorage copy of workspace/video, not just in-memory state", () => {
    // This is the specific failure mode to guard against: clearing
    // in-memory state via set() looks like it worked, but if the
    // persisted localStorage snapshot were somehow stale, a page reload
    // (or a naive read of localStorage) could still leak the previous
    // user's workspace. Zustand's persist middleware re-runs partialize
    // and rewrites storage on every set() call, including this one, so
    // there is no separate "also clear storage" step to forget — verified
    // here by reading raw localStorage directly, not just calling
    // useAppStore.getState() again (which only proves the in-memory copy).
    useAppStore.getState().setWorkspace({ id: "ws-1", name: "DBMS" });
    useAppStore.getState().setActiveMedia("file-1");
    useAppStore.getState().setVideoTimestamp(500);

    let persisted = JSON.parse(localStorage.getItem("app-store") as string).state;
    expect(persisted.workspace).toEqual({ id: "ws-1", name: "DBMS" });
    expect(persisted.video.activeMediaId).toBe("file-1");

    useAppStore.getState().logout();

    persisted = JSON.parse(localStorage.getItem("app-store") as string).state;
    expect(persisted.workspace).toBeNull();
    expect(persisted.video.activeMediaId).toBeNull();
    expect(persisted.video.currentTimestamp).toBe(0);
  });
});

describe("App_Store — persistence round-trip (Property 14)", () => {
  it("persists only workspace, ui, and video.{currentTimestamp,activeMediaId} to localStorage", () => {
    useAppStore.getState().setSession({ userId: "user-1" });
    useAppStore.getState().setWorkspace({ id: "ws-1", name: "DBMS" });
    useAppStore.getState().setActivePanel("video");
    useAppStore.getState().setVideoTimestamp(1935);
    useAppStore.getState().setActiveMedia("file-1");
    useAppStore.getState().setVideoPlaying(true);
    useAppStore.getState().addMessage({
      id: "m1",
      role: "user",
      content: "should not persist",
      timestamp: new Date(),
      status: "complete",
    });
    useAppStore.getState().addUpload("u1", {
      id: "u1",
      fileName: "a.pdf",
      fileType: "pdf",
      fileSize: 10,
      uploadDate: new Date(),
      progress: 50,
      estimatedTimeRemaining: 5,
      status: "uploading",
      fileRef: null,
    });

    const raw = localStorage.getItem("app-store");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw as string).state;

    // Critical state IS persisted, per Property 14.
    expect(persisted.workspace).toEqual({ id: "ws-1", name: "DBMS" });
    expect(persisted.ui).toEqual({ activePanel: "video", sidebarOpen: true });
    expect(persisted.video).toEqual({ currentTimestamp: 1935, activeMediaId: "file-1" });

    // Session, chat, and uploads are deliberately NOT persisted (matches
    // the Accion Labs document's own partialize sample) — session
    // security-sensitivity and Property 14's explicit "critical state"
    // list (workspace id, UI prefs, video timestamp, active media only).
    expect(persisted.session).toBeUndefined();
    expect(persisted.chat).toBeUndefined();
    expect(persisted.uploads).toBeUndefined();
    // isPlaying/duration are part of `video` but not in Property 14's
    // critical-state list, so they're excluded even though currentTimestamp
    // and activeMediaId (siblings on the same object) are included.
    expect(persisted.video.isPlaying).toBeUndefined();
    expect(persisted.video.duration).toBeUndefined();
  });
});

describe("App_Store — selective slice subscription (Property 15)", () => {
  it("a selector subscribed to one slice does not fire when a different slice updates", () => {
    let videoSelectorCalls = 0;
    const unsubscribe = useAppStore.subscribe(
      (state) => state.video.currentTimestamp,
      () => {
        videoSelectorCalls += 1;
      }
    );

    useAppStore.getState().setActivePanel("video"); // ui slice, not video
    useAppStore.getState().addMessage({
      id: "m1",
      role: "user",
      content: "hi",
      timestamp: new Date(),
      status: "complete",
    }); // chat slice, not video

    expect(videoSelectorCalls).toBe(0);

    useAppStore.getState().setVideoTimestamp(42); // video slice — should fire
    expect(videoSelectorCalls).toBe(1);

    unsubscribe();
  });
});
