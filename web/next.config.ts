import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a small self-contained server for the Docker image.
  output: "standalone",
  // A year of Zerodha tradebook rows can pass the default 1 MB.
  experimental: { serverActions: { bodySizeLimit: "10mb" } },
};

export default nextConfig;
