/**
 * Hand-gesture recognizer for WebXR hand tracking (Meta Quest).
 *
 * Pure TypeScript — no three.js / React — so it can be unit-tested with synthetic
 * joint poses. Feed it one `GestureFrame` per XR frame; it returns the discrete
 * gesture events that fired on that frame.
 *
 * Coordinates are metres in the XR reference space (`local-floor`), +Y up.
 * Joint names follow the WebXR Hand Input spec (e.g. "index-finger-tip").
 */

export type Vec3 = { x: number; y: number; z: number };
export type Handedness = "left" | "right";
export type HandJoints = Partial<Record<XRHandJoint, Vec3>>;

export interface HeadPose {
  position: Vec3;
  forward: Vec3; // unit vector the user is looking along
  up: Vec3; // unit vector, head up
  right: Vec3; // unit vector, head right
}

export interface GestureFrame {
  time: number; // ms, monotonic
  head: HeadPose;
  left?: HandJoints;
  right?: HandJoints;
}

export type GestureEvent =
  | { type: "palm-hold"; hand: Handedness } // open palm facing user, held → start voice
  | { type: "stop" } // both palms facing out → end / cancel
  | { type: "shush"; hand: Handedness } // index finger to lips → mute toggle
  | { type: "quick-fist"; hand: Handedness } // open → fist → open quickly → interrupt agent
  | { type: "fist-hold"; hand: Handedness } // fist held → recenter
  | { type: "thumbs-up"; hand: Handedness }
  | { type: "thumbs-down"; hand: Handedness }
  | { type: "swipe"; hand: Handedness; direction: "left" | "right" | "up" | "down" }
  | { type: "count"; hand: Handedness; count: 1 | 2 | 3 | 4 }; // fingers held up → pick option 1–4

/** "open" = all fingers + thumb out; "four" = four fingers out with the thumb tucked. */
export type HandPose =
  | "none"
  | "open"
  | "four"
  | "three"
  | "two"
  | "point"
  | "fist"
  | "thumbs-up"
  | "thumbs-down"
  | "other";

export const isOpenHand = (pose: HandPose) => pose === "open" || pose === "four";

export interface HandSnapshot {
  tracked: boolean;
  pose: HandPose;
  pinching: boolean;
  palmFacing: "user" | "away" | "neither";
  pinchPoint?: Vec3;
}

/** Thresholds — tune on device. Distances in metres, times in ms. */
export const GESTURE_TUNING = {
  pinchDistance: 0.02,
  pinchReleaseDistance: 0.035,
  fingerExtendedRatio: 1.5, // wrist→tip / wrist→proximal
  fingerCurledRatio: 1.15,
  thumbExtendedDistance: 0.06, // thumb tip ↔ index proximal
  thumbVertical: 0.6, // |dot(thumb dir, world up)|
  palmFacingDot: 0.5,
  stillSpeed: 0.35, // m/s — holds require the hand to be roughly still

  palmHoldMs: 1000,
  stopHoldMs: 600,
  shushHoldMs: 400,
  shushRadius: 0.08,
  mouthDown: 0.09, // mouth sits this far below the headset origin…
  mouthForward: 0.03, // …and this far in front of it
  thumbHoldMs: 500,
  countHoldMs: 700,
  fistHoldMs: 2000,
  quickFistMinMs: 80,
  quickFistMaxMs: 600,

  swipeWindowMs: 300,
  swipeDistance: 0.22,
  swipeDominance: 2, // primary axis must be this × the other axis
  maxFrameJump: 0.08, // a per-frame wrist jump larger than this is a tracking glitch, not a swipe

  eventCooldownMs: 700,
  swipeCooldownMs: 800,
} as const;

const T = GESTURE_TUNING;

// ---------------------------------------------------------------- vector math

const sub = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const dot = (a: Vec3, b: Vec3) => a.x * b.x + a.y * b.y + a.z * b.z;
const len = (a: Vec3) => Math.sqrt(dot(a, a));
const dist = (a: Vec3, b: Vec3) => len(sub(a, b));
const norm = (a: Vec3): Vec3 => {
  const l = len(a) || 1;
  return { x: a.x / l, y: a.y / l, z: a.z / l };
};
const cross = (a: Vec3, b: Vec3): Vec3 => ({
  x: a.y * b.z - a.z * b.y,
  y: a.z * b.x - a.x * b.z,
  z: a.x * b.y - a.y * b.x,
});
const addScaled = (a: Vec3, b: Vec3, s: number): Vec3 => ({ x: a.x + b.x * s, y: a.y + b.y * s, z: a.z + b.z * s });

// ------------------------------------------------------------ pose analysis

const FINGERS = ["index", "middle", "ring", "pinky"] as const;
type Finger = (typeof FINGERS)[number];
type FingerState = "extended" | "curled" | "between";

function fingerState(j: HandJoints, f: Finger): FingerState | null {
  const wrist = j.wrist;
  const prox = j[`${f}-finger-phalanx-proximal`];
  const tip = j[`${f}-finger-tip`];
  if (!wrist || !prox || !tip) return null;
  const ratio = dist(wrist, tip) / (dist(wrist, prox) || 1);
  if (ratio > T.fingerExtendedRatio) return "extended";
  if (ratio < T.fingerCurledRatio) return "curled";
  return "between";
}

/** Unit normal pointing out of the palm. */
export function palmNormal(j: HandJoints, hand: Handedness): Vec3 | null {
  const { wrist } = j;
  const index = j["index-finger-phalanx-proximal"];
  const pinky = j["pinky-finger-phalanx-proximal"];
  if (!wrist || !index || !pinky) return null;
  const n = norm(cross(sub(index, wrist), sub(pinky, wrist)));
  // The cross product points out of the palm for the right hand; mirrored for the left.
  return hand === "right" ? n : { x: -n.x, y: -n.y, z: -n.z };
}

export function analyzeHand(j: HandJoints | undefined, hand: Handedness, head: HeadPose): HandSnapshot {
  if (!j || !j.wrist) return { tracked: false, pose: "none", pinching: false, palmFacing: "neither" };

  const states = FINGERS.map((f) => fingerState(j, f));
  const thumbTip = j["thumb-tip"];
  const thumbBase = j["thumb-metacarpal"];
  const indexTip = j["index-finger-tip"];
  const indexProx = j["index-finger-phalanx-proximal"];

  const pinchDist = thumbTip && indexTip ? dist(thumbTip, indexTip) : Infinity;
  const pinching = pinchDist < T.pinchDistance;
  const pinchPoint =
    thumbTip && indexTip
      ? { x: (thumbTip.x + indexTip.x) / 2, y: (thumbTip.y + indexTip.y) / 2, z: (thumbTip.z + indexTip.z) / 2 }
      : undefined;

  const thumbExtended = !!thumbTip && !!indexProx && dist(thumbTip, indexProx) > T.thumbExtendedDistance;
  const thumbUpDot = thumbTip && thumbBase ? norm(sub(thumbTip, thumbBase)).y : 0;

  const allExtended = states.every((s) => s === "extended");
  const allCurled = states.every((s) => s === "curled");
  const othersCurled = states.slice(1).every((s) => s === "curled");

  const [index, middle, ring, pinky] = states;
  let pose: HandPose = "other";
  if (allExtended && !pinching) pose = thumbExtended ? "open" : "four";
  else if (allCurled && thumbExtended && thumbUpDot > T.thumbVertical) pose = "thumbs-up";
  else if (allCurled && thumbExtended && thumbUpDot < -T.thumbVertical) pose = "thumbs-down";
  else if (allCurled) pose = "fist";
  else if (index === "extended" && othersCurled) pose = "point";
  else if (index === "extended" && middle === "extended" && ring === "curled" && pinky === "curled") pose = "two";
  else if (index === "extended" && middle === "extended" && ring === "extended" && pinky === "curled") pose = "three";

  // Compare against the view direction rather than the hand→head vector, so hands
  // held off to the side still read as facing the user / away.
  let palmFacing: HandSnapshot["palmFacing"] = "neither";
  const n = palmNormal(j, hand);
  if (n) {
    const d = -dot(n, head.forward);
    if (d > T.palmFacingDot) palmFacing = "user";
    else if (d < -T.palmFacingDot) palmFacing = "away";
  }

  return { tracked: true, pose, pinching, palmFacing, pinchPoint };
}

// ---------------------------------------------------------------- recognizer

type HoldKey =
  | "palm-hold"
  | "shush"
  | "thumbs-up"
  | "thumbs-down"
  | "fist-hold"
  | "count-1"
  | "count-2"
  | "count-3"
  | "count-4";

interface HandTrack {
  // Pose currently being held + when it started; `fired` latches so a hold fires once.
  holdKey: string | null;
  holdStart: number;
  fired: boolean;
  // Quick-fist tracking.
  wasOpen: boolean;
  fistStart: number | null;
  // Wrist history for swipes + speed.
  history: { t: number; p: Vec3 }[];
  lastSwipe: number;
}

const newTrack = (): HandTrack => ({
  holdKey: null,
  holdStart: 0,
  fired: false,
  wasOpen: false,
  fistStart: null,
  history: [],
  lastSwipe: -Infinity,
});

export class GestureRecognizer {
  private tracks: Record<Handedness, HandTrack> = { left: newTrack(), right: newTrack() };
  private stopStart: number | null = null;
  private stopFired = false;
  private lastEvent = -Infinity;

  /** Latest per-hand analysis, for HUDs and two-hand interactions. */
  snapshot: Record<Handedness, HandSnapshot> = {
    left: { tracked: false, pose: "none", pinching: false, palmFacing: "neither" },
    right: { tracked: false, pose: "none", pinching: false, palmFacing: "neither" },
  };

  reset() {
    this.tracks = { left: newTrack(), right: newTrack() };
    this.stopStart = null;
    this.stopFired = false;
  }

  update(frame: GestureFrame): GestureEvent[] {
    const events: GestureEvent[] = [];
    const { time, head } = frame;

    const left = analyzeHand(frame.left, "left", head);
    const right = analyzeHand(frame.right, "right", head);
    this.snapshot = { left, right };

    // ---- Two-hand "stop": both palms open and facing away from the user.
    const stopPose =
      isOpenHand(left.pose) && isOpenHand(right.pose) && left.palmFacing === "away" && right.palmFacing === "away";
    if (stopPose) {
      this.stopStart ??= time;
      if (!this.stopFired && time - this.stopStart >= T.stopHoldMs) {
        this.stopFired = true;
        this.emit(events, { type: "stop" }, time);
      }
    } else {
      this.stopStart = null;
      this.stopFired = false;
    }

    for (const hand of ["left", "right"] as const) {
      const joints = frame[hand];
      const snap = hand === "left" ? left : right;
      const track = this.tracks[hand];

      if (!snap.tracked || !joints?.wrist) {
        this.tracks[hand] = newTrack();
        continue;
      }

      // Wrist history (trim to the swipe window).
      track.history.push({ t: time, p: joints.wrist });
      while (track.history.length && time - track.history[0].t > T.swipeWindowMs) track.history.shift();
      const speed = this.speed(track);

      // ---- Quick fist: open → fist → open within the window.
      if (snap.pose === "fist") {
        if (track.fistStart === null && track.wasOpen) track.fistStart = time;
      } else if (isOpenHand(snap.pose)) {
        if (track.fistStart !== null) {
          const held = time - track.fistStart;
          if (held >= T.quickFistMinMs && held <= T.quickFistMaxMs) {
            this.emit(events, { type: "quick-fist", hand }, time);
          }
        }
        track.fistStart = null;
        track.wasOpen = true;
      } else if (snap.pose !== "other") {
        // Any other definite pose breaks the open→fist→open sequence.
        track.fistStart = null;
        track.wasOpen = false;
      }

      // ---- Swipes: open hand moving fast along the head's right/up axes.
      if (isOpenHand(snap.pose) && !stopPose) {
        const swipe = this.detectSwipe(track, head, time);
        if (swipe) {
          track.lastSwipe = time;
          track.history = [];
          track.holdKey = null;
          this.emit(events, { type: "swipe", hand, direction: swipe }, time, true);
          continue;
        }
      }

      // ---- Single-hand holds.
      const holdKey = this.holdKeyFor(snap, joints, head, stopPose);
      if (holdKey !== track.holdKey) {
        track.holdKey = holdKey;
        track.holdStart = time;
        track.fired = false;
      }
      if (!holdKey || track.fired || speed > T.stillSpeed) {
        if (speed > T.stillSpeed) track.holdStart = time; // restart the timer while moving
        continue;
      }

      const held = time - track.holdStart;
      const need: Record<HoldKey, number> = {
        "count-1": T.countHoldMs,
        "count-2": T.countHoldMs,
        "count-3": T.countHoldMs,
        "count-4": T.countHoldMs,
        "palm-hold": T.palmHoldMs,
        shush: T.shushHoldMs,
        "thumbs-up": T.thumbHoldMs,
        "thumbs-down": T.thumbHoldMs,
        "fist-hold": T.fistHoldMs,
      };
      if (held >= need[holdKey]) {
        track.fired = true;
        if (holdKey === "fist-hold") track.fistStart = null; // a long hold is not a quick fist
        if (holdKey.startsWith("count-")) {
          const count = Number(holdKey.slice(6)) as 1 | 2 | 3 | 4;
          this.emit(events, { type: "count", hand, count }, time);
        } else {
          this.emit(events, { type: holdKey, hand } as GestureEvent, time);
        }
      }
    }

    return events;
  }

  private holdKeyFor(
    snap: HandSnapshot,
    j: HandJoints,
    head: HeadPose,
    stopPose: boolean,
  ): HoldKey | null {
    if (stopPose) return null;
    if (isOpenHand(snap.pose) && snap.palmFacing === "user") return "palm-hold";
    if (snap.pose === "thumbs-up") return "thumbs-up";
    if (snap.pose === "thumbs-down") return "thumbs-down";
    if (snap.pose === "fist") return "fist-hold";
    if (snap.pose === "point" && j["index-finger-tip"]) {
      const mouth = addScaled(addScaled(head.position, head.up, -T.mouthDown), head.forward, T.mouthForward);
      if (dist(j["index-finger-tip"], mouth) < T.shushRadius) return "shush";
    }
    // Finger counts are shown toward the panels, not the face.
    if (snap.palmFacing !== "user") {
      if (snap.pose === "point") return "count-1";
      if (snap.pose === "two") return "count-2";
      if (snap.pose === "three") return "count-3";
      if (snap.pose === "four") return "count-4";
    }
    return null;
  }

  private detectSwipe(track: HandTrack, head: HeadPose, time: number): "left" | "right" | "up" | "down" | null {
    if (time - track.lastSwipe < T.swipeCooldownMs || track.history.length < 2) return null;
    for (let i = 1; i < track.history.length; i++) {
      if (dist(track.history[i].p, track.history[i - 1].p) > T.maxFrameJump) return null;
    }
    const first = track.history[0];
    const last = track.history[track.history.length - 1];
    const delta = sub(last.p, first.p);
    const dx = dot(delta, head.right);
    const dy = dot(delta, head.up);
    if (Math.abs(dx) > T.swipeDistance && Math.abs(dx) > T.swipeDominance * Math.abs(dy)) {
      return dx > 0 ? "right" : "left";
    }
    if (Math.abs(dy) > T.swipeDistance && Math.abs(dy) > T.swipeDominance * Math.abs(dx)) {
      return dy > 0 ? "up" : "down";
    }
    return null;
  }

  private speed(track: HandTrack): number {
    const h = track.history;
    if (h.length < 2) return 0;
    const a = h[Math.max(0, h.length - 4)];
    const b = h[h.length - 1];
    const dt = (b.t - a.t) / 1000;
    return dt > 0 ? dist(a.p, b.p) / dt : 0;
  }

  private emit(events: GestureEvent[], e: GestureEvent, time: number, bypassCooldown = false) {
    if (!bypassCooldown && time - this.lastEvent < T.eventCooldownMs) return;
    this.lastEvent = time;
    events.push(e);
  }
}
