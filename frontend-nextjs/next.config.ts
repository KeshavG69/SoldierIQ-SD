import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Tree-shake large libraries
  experimental: {
    optimizePackageImports: [
      "framer-motion",
      "d3",
      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
      "@radix-ui/react-tooltip",
      "@radix-ui/react-scroll-area",
      "react-markdown",
      "remark-gfm",
      "markmap-lib",
      "markmap-view",
      "markmap-common",
      "jspdf",
      "@aws-sdk/client-s3",
      "@aws-sdk/s3-request-presigner",
    ],
  },

  // Turbopack config (use --turbopack flag when running dev)
  turbopack: {},

  webpack: (config) => {
    // The WebXR emulator (@react-three/xr → @iwer/sem) imports `@bufbuild/protobuf/wire`
    // (v2) without declaring it, so it resolves to LiveKit's hoisted v1, which has no
    // `/wire` export. Point that subpath at the v2 copy ts-proto installs.
    config.resolve.alias = {
      ...config.resolve.alias,
      "@bufbuild/protobuf/wire$": require.resolve("@bufbuild/protobuf/wire", {
        paths: [require.resolve("ts-proto")],
      }),
    };
    return config;
  },
};

export default nextConfig;
