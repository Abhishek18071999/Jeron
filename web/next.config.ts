import type { NextConfig } from "next";

// Sent with every page. Jeron is never shown inside another site's frame (clickjacking
// on the journal or Settings), files are never sniffed into another type, and links out
// don't carry Jeron's paths. Scripts are not limited by a script-src policy: Next.js's
// inline scripts would need a nonce on every page, and every script here is Jeron's own.
const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

const nextConfig: NextConfig = {
  // Produces a small self-contained server for the Docker image.
  output: "standalone",
  // A year of Zerodha tradebook rows, or a results CSV uploaded on Setup, pass 1 MB.
  experimental: { serverActions: { bodySizeLimit: "60mb" } },
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
