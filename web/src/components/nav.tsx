"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Five places: what to do today, a stock, my money, my record, and the research behind
// it all. Research pages (scanner, backtests, paper, compare, data, spot check) sit
// under one item.
export const RESEARCH_PATHS = ["/research", "/scanner", "/backtests", "/paper", "/compare", "/data", "/spot-check"];

type Item = { href: string; label: string; match: (path: string) => boolean; icon: React.ReactNode };

const icon = (d: string) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const starts = (path: string, prefix: string) => path === prefix || path.startsWith(`${prefix}/`);

export const NAV: Item[] = [
  { href: "/", label: "Today", match: (p) => p === "/", icon: icon("M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z") },
  { href: "/stocks", label: "Stocks", match: (p) => starts(p, "/stocks"), icon: icon("M4 19V9M10 19V5M16 19v-7M22 19H2") },
  { href: "/portfolio", label: "Portfolio", match: (p) => starts(p, "/portfolio"), icon: icon("M3 8h18v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM8 8V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v3M3 13h18") },
  { href: "/journal", label: "Journal", match: (p) => starts(p, "/journal"), icon: icon("M6 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM8 7h6M8 11h6M8 15h4") },
  { href: "/research", label: "Research", match: (p) => RESEARCH_PATHS.some((r) => starts(p, r)), icon: icon("M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4") },
];

export function TopNav() {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
      {NAV.map((item) => {
        const active = item.match(path);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              active ? "bg-surface-2 text-fg" : "text-muted hover:text-fg"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

// Phones: a fixed tab bar at the bottom, in thumb reach.
export function TabBar() {
  const path = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="mx-auto grid max-w-md grid-cols-5">
        {NAV.map((item) => {
          const active = item.match(path);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-0.5 py-2 text-[0.68rem] font-medium ${
                  active ? "text-accent" : "text-muted"
                }`}
              >
                {item.icon}
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
