"use client";

import { useEffect, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Quaternion, Vector3 } from "three";

import {
  GestureRecognizer,
  type GestureEvent,
  type GestureFrame,
  type HandJoints,
  type HeadPose,
} from "@/lib/xr/handGestures";
import { useVoiceStore } from "@/lib/stores/voiceStore";
import { useXRVoiceBridge } from "@/lib/stores/xrVoiceBridge";
import { useXRUi } from "@/lib/stores/xrUiStore";

const STOP_CONFIRM_MS = 4000;

const q = new Quaternion();
const fwd = new Vector3();
const up = new Vector3();
const right = new Vector3();

/** Shared with the debug HUD so it can show what the recognizer sees. */
export const gestureRecognizer = new GestureRecognizer();
export const latestHead: { pose: HeadPose | null } = { pose: null };

/**
 * Reads WebXR hand joints every frame, runs the recognizer, and maps gestures
 * to SoldierIQ actions (voice agent, menu, panel rig).
 */
export default function GestureController({ onStartVoice }: { onStartVoice: () => void }) {
  const startVoiceRef = useRef(onStartVoice);
  useEffect(() => {
    startVoiceRef.current = onStartVoice;
  }, [onStartVoice]);

  // Two-hand pinch → scale panels.
  const scaleGesture = useRef<{ startDist: number; startScale: number } | null>(null);

  useFrame((state, _delta, frame: XRFrame | undefined) => {
    const refSpace = state.gl.xr.getReferenceSpace();
    if (!frame || !refSpace) return;

    const viewer = frame.getViewerPose(refSpace);
    if (!viewer) return;
    const { position: p, orientation: o } = viewer.transform;
    q.set(o.x, o.y, o.z, o.w);
    fwd.set(0, 0, -1).applyQuaternion(q);
    up.set(0, 1, 0).applyQuaternion(q);
    right.set(1, 0, 0).applyQuaternion(q);
    const head: HeadPose = {
      position: { x: p.x, y: p.y, z: p.z },
      forward: { x: fwd.x, y: fwd.y, z: fwd.z },
      up: { x: up.x, y: up.y, z: up.z },
      right: { x: right.x, y: right.y, z: right.z },
    };
    latestHead.pose = head;

    const input: GestureFrame = { time: performance.now(), head };
    for (const source of frame.session.inputSources) {
      if (!source.hand || (source.handedness !== "left" && source.handedness !== "right")) continue;
      const joints: HandJoints = {};
      source.hand.forEach((space, name) => {
        const pose = frame.getJointPose?.(space, refSpace);
        if (pose) {
          const { x, y, z } = pose.transform.position;
          joints[name] = { x, y, z };
        }
      });
      input[source.handedness] = joints;
    }

    const events = gestureRecognizer.update(input);
    for (const e of events) handleGesture(e, startVoiceRef.current);

    // Two-hand pinch scale (continuous, not an event).
    const { left, right: r } = gestureRecognizer.snapshot;
    if (left.pinching && r.pinching && left.pinchPoint && r.pinchPoint) {
      const d = Math.hypot(
        left.pinchPoint.x - r.pinchPoint.x,
        left.pinchPoint.y - r.pinchPoint.y,
        left.pinchPoint.z - r.pinchPoint.z,
      );
      const ui = useXRUi.getState();
      if (!scaleGesture.current) scaleGesture.current = { startDist: d, startScale: ui.rigScale };
      else ui.setRigScale((scaleGesture.current.startScale * d) / scaleGesture.current.startDist);
    } else {
      scaleGesture.current = null;
    }
  });

  return null;
}

function handleGesture(e: GestureEvent, startVoice: () => void) {
  const ui = useXRUi.getState();
  const voice = useVoiceStore.getState();
  const bridge = useXRVoiceBridge.getState();
  const screen = ui.handlers;
  const inSession = voice.state === "connected";

  switch (e.type) {
    case "palm-hold":
      if (voice.state === "idle" || voice.state === "error") {
        ui.showToast("Starting voice agent…");
        startVoice();
      } else {
        ui.showToast("Voice agent is already on");
      }
      return;

    case "stop": {
      if (!inSession) {
        ui.setScreen("home");
        ui.showToast("Home");
        return;
      }
      const now = Date.now();
      if (now < ui.confirmStopUntil) {
        ui.setConfirmStopUntil(0);
        voice.stop();
        ui.showToast("Voice session ended");
      } else {
        ui.setConfirmStopUntil(now + STOP_CONFIRM_MS);
        ui.showToast("Show STOP again to end the session");
      }
      return;
    }

    case "shush":
      if (!inSession || !bridge.controls) return ui.showToast("Voice agent is not on");
      void bridge.controls.setMicEnabled(!bridge.micEnabled);
      ui.showToast(bridge.micEnabled ? "Mic muted" : "Mic on");
      return;

    case "quick-fist":
      if (!inSession || !bridge.controls) return;
      if (bridge.agentState === "speaking" || bridge.agentState === "thinking") {
        void bridge.controls.interrupt();
        ui.showToast("Interrupted - go ahead");
      }
      return;

    case "fist-hold":
      ui.recenter();
      ui.showToast("Recentered");
      return;

    case "count":
      if (screen?.choose?.(e.count)) ui.showToast(`Picked ${e.count}`);
      return;

    case "thumbs-up":
      // The open screen gets first call (submit answer, flip card, play/pause…).
      if (screen?.confirm?.()) return;
      if (!inSession || !bridge.controls) return;
      void bridge.controls.feedback("up");
      ui.showToast("Thanks - feedback sent");
      return;

    case "thumbs-down":
      if (!inSession || !bridge.controls) return;
      void bridge.controls.feedback("down");
      ui.showToast("Asking the agent to try again");
      return;

    case "swipe":
      if (e.direction === "up") {
        if (ui.screen !== "home") {
          ui.setScreen("home");
          ui.showToast("Home");
        }
      } else if (e.direction === "down") {
        if (screen?.back?.()) return;
        if (ui.screen !== "home") {
          ui.setScreen("home");
          ui.showToast("Home");
        }
      } else {
        const page = e.direction === "right" ? screen?.next : screen?.prev;
        if (!page) return; // nothing to page on this screen
        const forward = e.direction === "right";
        if (page()) ui.showToast(forward ? "Next >" : "< Previous");
        else ui.showToast(forward ? "That's the last one" : "That's the first one");
      }
      return;
  }
}
