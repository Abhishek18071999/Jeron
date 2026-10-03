import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { StockSearch } from "@/components/stock-search";

import "./globals.css";

export const metadata: Metadata = {
  title: "Jeron",
  description: "Personal research and decision support for Indian equities",
  appleWebApp: { capable: true, title: "Jeron", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = { themeColor: "#172554" };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <nav className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm">
            <Link href="/" className="font-semibold">
              Jeron
            </Link>
            <Link href="/journal">Journal</Link>
            <Link href="/scanner">Scanner</Link>
            <Link href="/backtests">Backtests</Link>
            <Link href="/paper">Paper trading</Link>
            <Link href="/data">Data quality</Link>
            <Link href="/spot-check">Spot check</Link>
            <StockSearch className="w-full sm:ml-auto sm:w-64" />
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
