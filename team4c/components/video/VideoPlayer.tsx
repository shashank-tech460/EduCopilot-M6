"use client";

import { useEffect, useRef, useState } from "react";
import videojs from "video.js";
import type Player from "video.js/dist/types/player";
import "video.js/dist/video-js.css";
// Side-effect import: registers the "youtube" tech with video.js so
// `techOrder: ["youtube", "html5"]` below actually has a YouTube
// implementation to select — video.js has no native YouTube support
// (confirmed: not in its own source), so Requirement 4.1's YouTube-URL
// clause is only satisfiable with this companion package. This is not a
// replacement for video.js — it's the standard technique the Accion Labs
// document's own `techOrder` reference implies.
import "videojs-youtube";

import { useAppStore } from "@/store/appStore";

interface VideoPlayerProps {
  fileId: string;
  type: "video" | "youtube_url";
  storageUrl: string;
  title: string;
}

/**
 * Video_Player — Accion Labs Requirement 4 (Interactive Video Player with
 * Chat Synchronization).
 *
 * 4.1 — MP4 (type: "video") and YouTube ("youtube_url") sources, via
 *       video.js `techOrder`.
 * 4.2 — seek commands are accepted via a Zustand subscription (per the
 *       spec's own component-design sample: "Accepts seek commands via a
 *       Zustand subscription or event dispatch"), not a prop/callback.
 *       Since nothing in the app dispatches a seek yet (that trigger is
 *       Source Attribution, Requirement 3, a later step — see this task's
 *       flagged conflict), this is verified directly by simulating a
 *       store update in tests, exactly as an eventual Source Attribution
 *       click would.
 * 4.3 — native `timeupdate` is forwarded to the store on every tick,
 *       which fires well within "1 second or less" between updates in
 *       any real browser — no artificial throttling needed or added.
 * 4.4 — the same handler also covers manual seeks (`seeked` event).
 * 4.5 — video.js's built-in control bar + `playbackRates` for 0.5x–2x.
 * 4.6 — `error` event renders an inline overlay with the failure reason.
 */
export function VideoPlayer({ fileId, type, storageUrl, title }: VideoPlayerProps) {
  // The wrapper div is the ONLY DOM node React manages here, and it is
  // never touched by video.js's dispose(). The actual <video> element is
  // created fresh (document.createElement) inside the effect below, on
  // every single effect run — this is the fix for the root cause:
  // reusing a React-owned <video> ref across multiple init/dispose cycles
  // meant the second `videojs()` call always received the same DOM node
  // that the *previous* `player.dispose()` had already torn down/detached
  // (video.js's dispose() actively dismantles the element structure it
  // wraps) — triggering "the element supplied is not included in the
  // DOM," on React Strict Mode's dev-mode double-invoke of effects on
  // mount AND on real navigation to a different file, since neither case
  // gave React a reason to create a genuinely new <video> node.
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<Player | null>(null);
  // Tracks the last timestamp *this component* wrote to the store, so the
  // seek-command subscription below can tell "an external seek command
  // arrived" apart from "this is just our own timeupdate echoing back" —
  // without this, every native timeupdate tick would look like an
  // incoming seek command and the player would fight itself.
  const lastReportedTimestamp = useRef(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    // A brand-new element every effect run — never the one a prior
    // dispose() already tore down.
    const videoElement = document.createElement("video");
    videoElement.className = "video-js";
    videoElement.setAttribute("aria-label", title);
    container.appendChild(videoElement);

    const player = videojs(videoElement, {
      controls: true,
      // `fill` (not `fluid`) is deliberate: `fluid` sizes the player using
      // the *video's own native dimensions*, so a portrait or unusually-
      // shaped video could make the whole dashboard panel excessively
      // tall. `fill` makes the player fill whatever container it's given
      // instead — the container's height is controlled by this
      // component's own CSS below (a fixed, reasonable height), and the
      // video letterboxes inside it via object-fit: contain (see the
      // .video-js-container-fill CSS rule in globals.css), preserving the
      // video's real aspect ratio without cropping or stretching it.
      fill: true,
      playbackRates: [0.5, 1, 1.25, 1.5, 2],
      techOrder: type === "youtube_url" ? ["youtube", "html5"] : ["html5"],
      sources: [
        {
          src: storageUrl,
          type: type === "youtube_url" ? "video/youtube" : "video/mp4",
        },
      ],
    });
    playerRef.current = player;
    setLoadError(null);

    useAppStore.getState().setActiveMedia(fileId);

    function reportTimestamp() {
      const seconds = player.currentTime() ?? 0;
      lastReportedTimestamp.current = seconds;
      useAppStore.getState().setVideoTimestamp(seconds);
    }

    player.on("loadedmetadata", () => {
      useAppStore.getState().setVideoDuration(player.duration() ?? 0);
    });
    player.on("timeupdate", reportTimestamp); // Requirement 4.3
    player.on("seeked", reportTimestamp); // Requirement 4.4 (manual seek)
    player.on("play", () => useAppStore.getState().setVideoPlaying(true));
    player.on("pause", () => useAppStore.getState().setVideoPlaying(false));
    player.on("error", () => {
      const err = player.error();
      setLoadError(
        err?.message ||
          "This video could not be loaded. Please re-upload the file or check the URL."
      );
    });

    return () => {
      // dispose() removes/tears down `videoElement` itself; the always-
      // present `container` div is untouched, so the next effect run (if
      // any) always has a valid, empty, attached parent to append a fresh
      // <video> element into.
      player.dispose();
      playerRef.current = null;
    };
  }, [fileId, type, storageUrl, title]);

  // Requirement 4.2 — seek command handling. Subscribed once; reads the
  // current player via the ref each time it fires, not a stale closure.
  useEffect(() => {
    const unsubscribe = useAppStore.subscribe(
      (state) => state.video.currentTimestamp,
      (newTimestamp) => {
        const player = playerRef.current;
        if (!player) {
          return;
        }
        const isExternalSeekCommand =
          Math.abs(newTimestamp - lastReportedTimestamp.current) > 0.5;
        if (isExternalSeekCommand) {
          player.currentTime(newTimestamp);
          player.play();
        }
      }
    );
    return unsubscribe;
  }, []);

  return (
    <div
      className="relative h-[280px] overflow-hidden rounded-md bg-black sm:h-[340px] md:h-[380px]"
      data-testid="video-player-container"
    >
      <div ref={containerRef} className="video-js-fill-container h-full w-full" />
      {loadError ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/80 p-4 text-center text-white">
          <p className="text-sm font-medium">{loadError}</p>
        </div>
      ) : null}
    </div>
  );
}
