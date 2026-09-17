"use client";

import { useEffect, useRef } from "react";
import { useAppStore } from "@/store/appStore";

export function useActiveConversation(workspaceId: string): string | null {
  const activeConversationId = useAppStore(
    (state) => state.chat.activeConversationId
  );
  const activeConversationWorkspaceId = useAppStore(
    (state) => state.chat.activeConversationWorkspaceId
  );
  const setActiveConversation = useAppStore(
    (state) => state.setActiveConversation
  );

  const creationInFlightForRef = useRef<string | null>(null);

  useEffect(() => {
    if (activeConversationWorkspaceId === workspaceId && activeConversationId) {
      return;
    }

    if (creationInFlightForRef.current === workspaceId) {
      return;
    }

    creationInFlightForRef.current = workspaceId;

    async function createConversation() {
      try {
        const response = await fetch(
          `/api/workspaces/${workspaceId}/conversations`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({}),
          }
        );

        if (!response.ok) {
          console.error(
            `[chat] Failed to create conversation: ${response.status} ${response.statusText}`
          );
          return;
        }

        const data: { id: string } = await response.json();

        setActiveConversation(data.id, workspaceId);
      } catch (error) {
        console.error("[chat] Conversation creation failed:", error);
      } finally {
        if (creationInFlightForRef.current === workspaceId) {
          creationInFlightForRef.current = null;
        }
      }
    }

    void createConversation();
  }, [
    workspaceId,
    activeConversationId,
    activeConversationWorkspaceId,
    setActiveConversation,
  ]);

  return activeConversationWorkspaceId === workspaceId
    ? activeConversationId
    : null;
}
