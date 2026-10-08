"use client";

import { Component, Suspense, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox, Text, useTexture } from "@react-three/drei";
import { Color, Mesh, SRGBColorSpace, type Texture } from "three";

import { useXRUi, type XRScreenHandlers } from "@/lib/stores/xrUiStore";

// Served locally so 3D text works offline (troika otherwise fetches fonts from a CDN).
export const FONT = "/fonts/NotoSans-Regular.ttf";

export const C = {
  panel: "#111418",
  border: "#2a2f36",
  button: "#1e232a",
  text: "#f2f4f7",
  muted: "#8b94a3",
  accent: "#2f6fe0",
  danger: "#e5484d",
  success: "#30c48d",
  warning: "#f5a524",
};

/** Main screen panel size (metres). */
export const SCREEN_W = 1.0;
export const SCREEN_H = 0.68;

/** Presigned media must be served with CORS to become a WebGL texture; route it through our proxy. */
export const mediaUrl = (url: string) => `/api/xr/media?url=${encodeURIComponent(url)}`;

const noRaycast = () => null;

/** Text that never intercepts the pointer ray, so labels drawn over buttons stay clickable. */
export function T(props: ComponentProps<typeof Text>) {
  return <Text font={FONT} color={C.text} anchorX="center" anchorY="middle" raycast={noRaycast} {...props} />;
}

export function Panel({
  width,
  height,
  children,
  position,
  rotation,
}: {
  width: number;
  height: number;
  children?: ReactNode;
  position?: [number, number, number];
  rotation?: [number, number, number];
}) {
  return (
    <group position={position} rotation={rotation}>
      <RoundedBox args={[width + 0.006, height + 0.006, 0.008]} radius={0.02} position={[0, 0, -0.002]}>
        <meshBasicMaterial color={C.border} />
      </RoundedBox>
      <RoundedBox args={[width, height, 0.01]} radius={0.018}>
        <meshBasicMaterial color={C.panel} />
      </RoundedBox>
      <group position={[0, 0, 0.007]}>{children}</group>
    </group>
  );
}

export function Button({
  label,
  onClick,
  position,
  width = 0.16,
  height = 0.05,
  color = C.button,
  textColor = C.text,
  fontSize = 0.018,
  disabled = false,
  align = "center",
}: {
  label: string;
  onClick: () => void;
  position: [number, number, number];
  width?: number;
  height?: number;
  color?: string;
  textColor?: string;
  fontSize?: number;
  disabled?: boolean;
  align?: "center" | "left";
}) {
  const [hover, setHover] = useState(false);
  const fill = disabled ? "#15191e" : hover ? new Color(color).offsetHSL(0, 0, 0.08) : color;
  return (
    <group position={position}>
      <RoundedBox
        args={[width, height, 0.012]}
        radius={Math.min(0.012, height / 3)}
        onClick={(e) => {
          e.stopPropagation();
          if (!disabled) onClick();
        }}
        onPointerOver={() => setHover(true)}
        onPointerOut={() => setHover(false)}
      >
        <meshBasicMaterial color={fill} />
      </RoundedBox>
      <T
        position={[align === "left" ? -width / 2 + 0.02 : 0, 0, 0.008]}
        anchorX={align === "left" ? "left" : "center"}
        fontSize={fontSize}
        color={disabled ? C.muted : textColor}
        maxWidth={width - 0.03}
        overflowWrap="break-word"
        textAlign={align}
      >
        {label}
      </T>
    </group>
  );
}

export function Spinner({ position, size = 0.04 }: { position?: [number, number, number]; size?: number }) {
  const ref = useRef<Mesh>(null);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.z -= dt * 4;
  });
  return (
    <mesh ref={ref} position={position}>
      <ringGeometry args={[size * 0.7, size, 32, 1, 0, Math.PI * 1.5]} />
      <meshBasicMaterial color={C.accent} />
    </mesh>
  );
}

/** Centered spinner + message for loading / processing states. */
export function Busy({ text, y = 0 }: { text: string; y?: number }) {
  return (
    <group position={[0, y, 0]}>
      <Spinner position={[0, 0.04, 0]} />
      <T position={[0, -0.04, 0]} fontSize={0.022} color={C.muted} maxWidth={SCREEN_W - 0.1} textAlign="center">
        {text}
      </T>
    </group>
  );
}

/** Title row shared by every screen, with Home (and optionally Back) buttons. */
export function ScreenHeader({
  title,
  subtitle,
  onBack,
  backLabel = "Back",
}: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  backLabel?: string;
}) {
  const setScreen = useXRUi((s) => s.setScreen);
  const top = SCREEN_H / 2;
  const textW = SCREEN_W - (onBack ? 0.45 : 0.2);
  return (
    <group>
      <T position={[-SCREEN_W / 2 + 0.04, top - 0.05, 0]} anchorX="left" fontSize={0.028} maxWidth={textW} whiteSpace="nowrap" clipRect={[0, -0.05, textW, 0.05]}>
        {title}
      </T>
      {subtitle && (
        <T position={[-SCREEN_W / 2 + 0.04, top - 0.088, 0]} anchorX="left" fontSize={0.015} color={C.muted} maxWidth={SCREEN_W - 0.08}>
          {subtitle}
        </T>
      )}
      {onBack && (
        <Button label={backLabel} width={0.15} height={0.042} position={[SCREEN_W / 2 - 0.23, top - 0.055, 0]} onClick={onBack} />
      )}
      <Button label="Home" width={0.11} height={0.042} position={[SCREEN_W / 2 - 0.08, top - 0.055, 0]} onClick={() => setScreen("home")} />
    </group>
  );
}

/**
 * Registers the active screen's gesture handlers while mounted. Handlers may change
 * every render; the registered wrappers always call the latest ones.
 */
export function useScreenHandlers(handlers: XRScreenHandlers) {
  const ref = useRef(handlers);
  ref.current = handlers;
  const keys = Object.keys(handlers).sort().join(",");

  useEffect(() => {
    const wrapped: XRScreenHandlers = {};
    for (const k of keys.split(",").filter(Boolean) as (keyof XRScreenHandlers)[]) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (wrapped as any)[k] = (...args: any[]) => (ref.current[k] as any)?.(...args);
    }
    useXRUi.getState().setHandlers(wrapped);
    return () => {
      if (useXRUi.getState().handlers === wrapped) useXRUi.getState().setHandlers(null);
    };
  }, [keys]);
}

/** Paging helper: clamps to [0, count) and exposes next/prev that report whether they moved. */
export function usePager(count: number, resetKey?: unknown) {
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [resetKey]);
  const clamped = Math.min(page, Math.max(0, count - 1));
  return {
    page: clamped,
    setPage,
    next: () => {
      if (clamped >= count - 1) return false;
      setPage(clamped + 1);
      return true;
    },
    prev: () => {
      if (clamped <= 0) return false;
      setPage(clamped - 1);
      return true;
    },
  };
}

function FittedImage({ url, maxW, maxH }: { url: string; maxW: number; maxH: number }) {
  const texture = useTexture(mediaUrl(url)) as Texture;
  texture.colorSpace = SRGBColorSpace;
  const img = texture.image as { width: number; height: number } | undefined;
  const aspect = img && img.height ? img.width / img.height : 16 / 9;
  const [w, h] = aspect > maxW / maxH ? [maxW, maxW / aspect] : [maxH * aspect, maxH];
  return (
    <mesh>
      <planeGeometry args={[w, h]} />
      <meshBasicMaterial map={texture} toneMapped={false} />
    </mesh>
  );
}

/** An image from a (presigned) URL, scaled to fit within maxW × maxH. */
export function MediaImage({
  url,
  maxW,
  maxH,
  position,
}: {
  url: string;
  maxW: number;
  maxH: number;
  position?: [number, number, number];
}) {
  return (
    <group position={position}>
      <ImageErrorBoundary key={url}>
        <Suspense fallback={<Spinner />}>
          <FittedImage url={url} maxW={maxW} maxH={maxH} />
        </Suspense>
      </ImageErrorBoundary>
    </group>
  );
}

class ImageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return (
        <T fontSize={0.018} color={C.danger}>
          Could not load image
        </T>
      );
    }
    return this.props.children;
  }
}

export interface SavedItem {
  id: string;
  title: string;
  subtitle?: string;
  disabled?: boolean;
}

const LIST_ROWS = 5;

/**
 * "Generate new" + paged list of saved items. Swipe left/right pages the list;
 * fingers 1–4 open the matching row on the current page.
 */
export function SavedList({
  items,
  loading,
  onOpen,
  onGenerate,
  generateLabel,
  generating,
  canGenerate,
  emptyText,
  error,
}: {
  items: SavedItem[];
  loading?: boolean;
  onOpen: (id: string) => void;
  onGenerate?: () => void;
  generateLabel?: string;
  generating?: boolean;
  canGenerate: boolean;
  emptyText: string;
  error?: string | null;
}) {
  const setScreen = useXRUi((s) => s.setScreen);
  const pages = Math.max(1, Math.ceil(items.length / LIST_ROWS));
  const pager = usePager(pages, items.length);
  const rows = items.slice(pager.page * LIST_ROWS, pager.page * LIST_ROWS + LIST_ROWS);

  useScreenHandlers({
    next: pager.next,
    prev: pager.prev,
    choose: (n) => {
      const row = rows[n - 1];
      if (!row || row.disabled) return false;
      onOpen(row.id);
      return true;
    },
  });

  const top = SCREEN_H / 2 - 0.15;
  return (
    <group>
      {onGenerate && (
        <>
          <Button
            label={generating ? "Starting…" : generateLabel ?? "Generate new"}
            width={0.32}
            color={C.accent}
            disabled={!canGenerate || generating}
            position={[-SCREEN_W / 2 + 0.2, top, 0]}
            onClick={onGenerate}
          />
          {!canGenerate && (
            <Button
              label="Select documents"
              width={0.26}
              position={[-SCREEN_W / 2 + 0.52, top, 0]}
              onClick={() => setScreen("documents")}
            />
          )}
        </>
      )}
      {error && (
        <T position={[0, top - 0.06, 0]} fontSize={0.016} color={C.danger} maxWidth={SCREEN_W - 0.1}>
          {error}
        </T>
      )}
      {loading ? (
        <Busy text="Loading…" y={-0.05} />
      ) : items.length === 0 ? (
        <T position={[0, -0.05, 0]} fontSize={0.02} color={C.muted} maxWidth={SCREEN_W - 0.1} textAlign="center">
          {emptyText}
        </T>
      ) : (
        <>
          {rows.map((item, i) => (
            <group key={item.id} position={[0, top - 0.1 - i * 0.07, 0]}>
              <T position={[-SCREEN_W / 2 + 0.05, 0, 0]} fontSize={0.016} color={C.muted}>
                {i + 1}
              </T>
              <Button
                label={item.subtitle ? `${item.title}   ·   ${item.subtitle}` : item.title}
                width={SCREEN_W - 0.14}
                height={0.056}
                align="left"
                disabled={item.disabled}
                position={[0.03, 0, 0]}
                onClick={() => onOpen(item.id)}
              />
            </group>
          ))}
          {pages > 1 && (
            <T position={[0, -SCREEN_H / 2 + 0.04, 0]} fontSize={0.014} color={C.muted}>
              {`Page ${pager.page + 1} / ${pages} · swipe to change page`}
            </T>
          )}
        </>
      )}
    </group>
  );
}

/** Plain-text pages from markdown, sized for a panel. */
export function paginate(markdown: string, charsPerPage = 750): string[] {
  const text = markdown
    .replace(/```[\s\S]*?```/g, "")
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/[*_`>]/g, "")
    .replace(/\[\d+(,\s*\d+)*]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  // Fill each page word by word (spaces only, so list line breaks survive) and keep paragraph gaps.
  const pages: string[] = [];
  let cur = "";
  for (const para of text.split(/\n\n/)) {
    let sep = cur ? "\n\n" : "";
    for (const word of para.split(/ +/)) {
      if (cur && (cur + sep + word).length > charsPerPage) {
        pages.push(cur.trim());
        cur = "";
        sep = "";
      }
      cur += sep + word;
      sep = " ";
    }
  }
  if (cur.trim()) pages.push(cur.trim());
  return pages.length ? pages : [""];
}

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
