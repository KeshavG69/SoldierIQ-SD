"use client";

import { Component, Suspense, useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { XRSpace, useXR, useXRInputSourceState } from "@react-three/xr";
import { Group, Mesh, MeshStandardMaterial, Vector3 } from "three";

import GestureController, { gestureRecognizer, latestHead } from "./GestureController";
import { Busy, Button, C, Panel, SCREEN_H, SCREEN_W, T } from "./ui";
import HomeScreen from "./screens/HomeScreen";
import DocumentsScreen from "./screens/DocumentsScreen";
import QuizScreen from "./screens/QuizScreen";
import SlidesScreen from "./screens/SlidesScreen";
import FlashcardsScreen from "./screens/FlashcardsScreen";
import InfographicScreen from "./screens/InfographicScreen";
import MindMapScreen from "./screens/MindMapScreen";
import VideoScreen from "./screens/VideoScreen";
import AudioScreen from "./screens/AudioScreen";
import ReportsScreen from "./screens/ReportsScreen";
import { useVoiceStore } from "@/lib/stores/voiceStore";
import { useXRVoiceBridge, type AgentUiState } from "@/lib/stores/xrVoiceBridge";
import { useXRUi, type XRScreen } from "@/lib/stores/xrUiStore";

const SCREENS: Record<XRScreen, ComponentType> = {
  home: HomeScreen,
  documents: DocumentsScreen,
  quiz: QuizScreen,
  slides: SlidesScreen,
  flashcards: FlashcardsScreen,
  infographic: InfographicScreen,
  mindmap: MindMapScreen,
  video: VideoScreen,
  audio: AudioScreen,
  reports: ReportsScreen,
};

const STATE_COLORS: Record<AgentUiState | "off", string> = {
  off: "#3a3f47",
  disconnected: "#3a3f47",
  unknown: "#3a3f47",
  connecting: "#8b94a3",
  initializing: "#8b94a3",
  listening: "#4f8cff",
  thinking: "#f5a524",
  speaking: "#30c48d",
};

const STATE_LABELS: Record<AgentUiState | "off", string> = {
  off: "Voice agent off",
  disconnected: "Disconnected",
  unknown: "Ready",
  connecting: "Connecting…",
  initializing: "Starting up…",
  listening: "Listening",
  thinking: "Thinking…",
  speaking: "Speaking",
};

interface XRSceneProps {
  documentCount: number;
  onStartVoice: () => void;
  debug: boolean;
}

export default function XRScene({ documentCount, onStartVoice, debug }: XRSceneProps) {
  return (
    <Suspense fallback={null}>
      <ambientLight intensity={0.8} />
      <directionalLight position={[1, 3, 2]} intensity={1.2} />
      <GestureController onStartVoice={onStartVoice} />
      <PanelRig>
        <ScreenPanel />
        {/* Voice agent rides alongside every screen, angled toward the user. */}
        <group position={[-SCREEN_W / 2 - 0.26, 0, 0.1]} rotation={[0, 0.45, 0]}>
          <VoicePanel documentCount={documentCount} onStartVoice={onStartVoice} />
          <StopConfirm />
        </group>
      </PanelRig>
      <HeadLocked>
        <ToastView />
        {debug && <DebugHud />}
      </HeadLocked>
      <WristMicBadge />
    </Suspense>
  );
}

// ------------------------------------------------------------------ rig

/** Group of panels floating in front of the user; recenters on demand and scales with two-hand pinch. */
function PanelRig({ children }: { children: ReactNode }) {
  const ref = useRef<Group>(null);
  const session = useXR((s) => s.session);
  const recenterNonce = useXRUi((s) => s.recenterNonce);
  const rigScale = useXRUi((s) => s.rigScale);
  const pending = useRef(true);

  useEffect(() => {
    pending.current = true;
  }, [recenterNonce, session]);

  useFrame(() => {
    const g = ref.current;
    if (!g) return;
    g.scale.setScalar(rigScale);
    const head = latestHead.pose;
    if (!pending.current || !head) return;
    pending.current = false;
    const flat = new Vector3(head.forward.x, 0, head.forward.z);
    if (flat.lengthSq() < 1e-4) flat.set(0, 0, -1);
    flat.normalize();
    g.position.set(head.position.x + flat.x * 1.0, head.position.y - 0.12, head.position.z + flat.z * 1.0);
    g.rotation.set(0, Math.atan2(flat.x, flat.z) + Math.PI, 0);
  });

  // Outside XR (desktop preview) sit in front of the default camera.
  return (
    <group ref={ref} position={[0, 1.48, -1.0]}>
      {children}
    </group>
  );
}

/** Children follow the user's view, slightly below centre. */
function HeadLocked({ children }: { children: ReactNode }) {
  const ref = useRef<Group>(null);
  const target = useRef(new Vector3());
  useFrame((state) => {
    const g = ref.current;
    if (!g) return;
    const cam = state.camera;
    target.current.set(0, -0.22, -0.75).applyQuaternion(cam.getWorldQuaternion(g.quaternion));
    target.current.add(cam.getWorldPosition(new Vector3()));
    g.position.lerp(target.current, 0.25);
  });
  return <group ref={ref}>{children}</group>;
}

// --------------------------------------------------------------- widgets

function ScreenPanel() {
  const screen = useXRUi((s) => s.screen);
  const Screen = SCREENS[screen];
  return (
    <Panel width={SCREEN_W} height={SCREEN_H}>
      <ScreenErrorBoundary key={screen}>
        <Suspense fallback={<Busy text="Loading…" />}>
          <Screen />
        </Suspense>
      </ScreenErrorBoundary>
    </Panel>
  );
}

class ScreenErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <group>
        <T position={[0, 0.05, 0]} fontSize={0.022} color={C.danger} maxWidth={SCREEN_W - 0.1}>
          {`Something went wrong: ${this.state.error.message}`}
        </T>
        <Button label="Home" width={0.14} position={[0, -0.05, 0]} onClick={() => useXRUi.getState().setScreen("home")} />
      </group>
    );
  }
}

function VoicePanel({ documentCount, onStartVoice }: { documentCount: number; onStartVoice: () => void }) {
  const voiceState = useVoiceStore((s) => s.state);
  const voiceError = useVoiceStore((s) => s.error);
  const stop = useVoiceStore((s) => s.stop);
  const agentState = useXRVoiceBridge((s) => s.agentState);
  const micEnabled = useXRVoiceBridge((s) => s.micEnabled);
  const controls = useXRVoiceBridge((s) => s.controls);

  const inSession = voiceState === "connected";
  const key: AgentUiState | "off" =
    voiceState === "fetching-token" ? "connecting" : inSession ? agentState : "off";
  const label = voiceState === "error" ? voiceError ?? "Voice error" : STATE_LABELS[key];

  return (
    <Panel width={0.4} height={0.5}>
      <T position={[0, 0.21, 0]} fontSize={0.016} color={C.muted} letterSpacing={0.15}>
        VOICE AGENT
      </T>
      <Orb color={STATE_COLORS[key]} state={key} position={[0, 0.1, 0.02]} />
      <T position={[0, -0.0, 0]} fontSize={0.026} color={voiceState === "error" ? C.danger : C.text} maxWidth={0.36} textAlign="center">
        {label}
      </T>
      <T position={[0, -0.045, 0]} fontSize={0.014} color={C.muted}>
        {inSession && !micEnabled
          ? "Your mic is muted"
          : `${documentCount} document${documentCount === 1 ? "" : "s"} in scope`}
      </T>
      {inSession ? (
        <>
          <Button label={micEnabled ? "Mute" : "Unmute"} width={0.17} position={[-0.095, -0.115, 0]} onClick={() => controls?.setMicEnabled(!micEnabled)} />
          <Button
            label="Interrupt"
            width={0.17}
            position={[0.095, -0.115, 0]}
            disabled={agentState !== "speaking" && agentState !== "thinking"}
            onClick={() => controls?.interrupt()}
          />
          <Button label="End call" width={0.36} color={C.danger} position={[0, -0.18, 0]} onClick={stop} />
        </>
      ) : (
        <>
          <Button
            label={voiceState === "fetching-token" ? "Connecting…" : "Start voice agent"}
            width={0.32}
            color={C.accent}
            position={[0, -0.13, 0]}
            disabled={voiceState === "fetching-token"}
            onClick={onStartVoice}
          />
          <T position={[0, -0.19, 0]} fontSize={0.013} color={C.muted}>
            or hold an open palm toward you
          </T>
        </>
      )}
    </Panel>
  );
}

function Orb({ color, state, position }: { color: string; state: AgentUiState | "off"; position: [number, number, number] }) {
  const ref = useRef<Mesh>(null);
  useFrame(({ clock }) => {
    const m = ref.current;
    if (!m) return;
    const t = clock.getElapsedTime();
    const amp = state === "speaking" ? 0.12 : state === "listening" ? 0.04 : state === "thinking" ? 0.07 : 0;
    const speed = state === "speaking" ? 9 : state === "thinking" ? 5 : 2;
    m.scale.setScalar(1 + Math.sin(t * speed) * amp);
    const mat = m.material as MeshStandardMaterial;
    mat.color.set(color);
    mat.emissive.set(color);
  });
  return (
    <mesh ref={ref} position={position}>
      <sphereGeometry args={[0.055, 48, 48]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} roughness={0.3} />
    </mesh>
  );
}

function StopConfirm() {
  const until = useXRUi((s) => s.confirmStopUntil);
  const setUntil = useXRUi((s) => s.setConfirmStopUntil);
  const stop = useVoiceStore((s) => s.stop);
  const [, force] = useState(0);

  useEffect(() => {
    if (until <= Date.now()) return;
    const t = setTimeout(() => force((n) => n + 1), until - Date.now() + 10);
    return () => clearTimeout(t);
  }, [until]);

  if (until <= Date.now()) return null;
  return (
    <Panel width={0.4} height={0.16} position={[0, -0.36, 0.05]}>
      <T position={[0, 0.035, 0]} fontSize={0.02}>
        End the voice session?
      </T>
      <Button
        label="End"
        width={0.15}
        color={C.danger}
        position={[-0.09, -0.035, 0]}
        onClick={() => {
          setUntil(0);
          stop();
        }}
      />
      <Button label="Keep talking" width={0.15} position={[0.09, -0.035, 0]} onClick={() => setUntil(0)} />
    </Panel>
  );
}

function ToastView() {
  const toast = useXRUi((s) => s.toast);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!toast) return;
    setVisible(true);
    const t = setTimeout(() => setVisible(false), 1800);
    return () => clearTimeout(t);
  }, [toast]);
  if (!toast || !visible) return null;
  return (
    <group>
      <RoundedBox args={[Math.max(0.18, toast.text.length * 0.0115 + 0.06), 0.05, 0.004]} radius={0.02}>
        <meshBasicMaterial color="#000000" transparent opacity={0.75} />
      </RoundedBox>
      <T position={[0, 0, 0.004]} fontSize={0.02}>
        {toast.text}
      </T>
    </group>
  );
}

function DebugHud() {
  const [text, setText] = useState("");
  useFrame(() => {
    const { left, right } = gestureRecognizer.snapshot;
    const fmt = (h: typeof left) => (h.tracked ? `${h.pose} ${h.pinching ? "pinch " : ""}palm:${h.palmFacing}` : "-");
    const next = `L ${fmt(left)}\nR ${fmt(right)}`;
    if (next !== text) setText(next);
  });
  return (
    <T position={[0, -0.07, 0]} fontSize={0.014} color="#ffd166" textAlign="center">
      {text}
    </T>
  );
}

/** Small "MIC OFF" badge on the left wrist while muted. */
function WristMicBadge() {
  const hand = useXRInputSourceState("hand", "left");
  const micEnabled = useXRVoiceBridge((s) => s.micEnabled);
  const inSession = useVoiceStore((s) => s.state === "connected");
  const wrist = hand?.inputSource.hand.get("wrist");
  if (!wrist || !inSession || micEnabled) return null;
  return (
    <XRSpace space={wrist}>
      <group position={[0, 0.03, 0.02]} rotation={[-Math.PI / 2, 0, 0]}>
        <RoundedBox args={[0.07, 0.024, 0.003]} radius={0.008}>
          <meshBasicMaterial color={C.danger} />
        </RoundedBox>
        <T position={[0, 0, 0.003]} fontSize={0.011} color="#ffffff">
          MIC OFF
        </T>
      </group>
    </XRSpace>
  );
}
