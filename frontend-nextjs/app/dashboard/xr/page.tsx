"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

// three.js + WebXR are browser-only.
const XRWorkspace = dynamic(() => import("@/components/xr/XRWorkspace"), { ssr: false });

export default function XRPage() {
  return (
    <Suspense fallback={null}>
      <XRWorkspace />
    </Suspense>
  );
}
