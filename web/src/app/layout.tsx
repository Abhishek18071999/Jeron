import type { Metadata, Viewport } from "next";
import Link from "next/link";

import { TabBar, TopNav } from "@/components/nav";
import { StockSearch } from "@/components/stock-search";

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
            <StockSearch className="ml-auto w-full max-w-[16rem] sm:max-w-xs" />
          </div>
        </header>
        {/* Room for the phone tab bar. */}
        <div className="pb-24 md:pb-8">{children}</div>
        <TabBar />
      </body>
    </html>
  );
}
