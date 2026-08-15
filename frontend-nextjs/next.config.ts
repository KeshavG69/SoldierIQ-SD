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
};

export default nextConfig;
