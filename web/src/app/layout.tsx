import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jeron",
  description: "Personal research and decision support for Indian equities",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <nav className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto flex max-w-6xl gap-6 px-4 py-3 text-sm">
            <Link href="/" className="font-semibold">
              Jeron
            </Link>
            <Link href="/scanner">Scanner</Link>
            <Link href="/backtests">Backtests</Link>
            <Link href="/data">Data quality</Link>
            <Link href="/spot-check">Spot check</Link>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
