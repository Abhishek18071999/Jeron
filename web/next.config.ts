import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a small self-contained server for the Docker image.
  output: "standalone",
  // A year of Zerodha tradebook rows, or a results CSV uploaded on Setup, pass 1 MB.
  experimental: { serverActions: { bodySizeLimit: "60mb" } },
};

export default nextConfig;
