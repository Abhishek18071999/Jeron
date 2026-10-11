import type { Metadata, Viewport } from "next";
import Link from "next/link";

import { CommandPalette } from "@/components/command-palette";
import { TabBar, TopNav } from "@/components/nav";
import { StockSearch } from "@/components/stock-search";
import { loginConfig } from "@/lib/auth";

import "./globals.css";

export const metadata: Metadata = {
  title: "Jeron",
  description: "Personal research and decision support for Indian equities",
  appleWebApp: { capable: true, title: "Jeron", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#16181b" },
  ],
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
            <Link href="/" className="text-base font-semibold tracking-tight">
              Jeron
            </Link>
            <TopNav />
            <StockSearch className="ml-auto hidden w-full max-w-xs md:block" />
            <CommandPalette />
            <Link href="/settings" aria-label="Settings" title="Settings" className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg">
              <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 6h10M18 6h2M16 4v4M4 12h2M10 12h10M8 10v4M4 18h10M18 18h2M16 16v4" />
              </svg>
            </Link>
          </div>
          {loginConfig().mode === "off" && (
            <p className="bg-warn-bg px-4 py-1 text-center text-xs text-warn">
              Login is off (JERON_LOGIN_DISABLED): anyone who can open this address sees your positions.
            </p>
          )}
        </header>
        {/* Room for the phone tab bar. */}
        <div className="pb-24 md:pb-8">{children}</div>
        <TabBar />
      </body>
    </html>
  );
}
