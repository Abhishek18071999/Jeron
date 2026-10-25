"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { StockSearch } from "@/components/stock-search";
import { MAX_COMPARE } from "@/lib/compare";

const href = (symbols: string[]) =>
  symbols.length ? `/stocks/compare?symbols=${encodeURIComponent(symbols.join(","))}` : "/stocks/compare";

// The stocks being compared, as chips, and the same search box as the header's: type a
// symbol, a company name, a short name or an old symbol and pick a suggestion.
export function ComparePicker({ symbols, names }: { symbols: string[]; names: Record<string, string | null> }) {
  const router = useRouter();
  const full = symbols.length >= MAX_COMPARE;
  const add = (symbol: string) => {
    const s = symbol.trim();
    if (!s || symbols.some((x) => x.toUpperCase() === s.toUpperCase())) return;
    router.push(href([...symbols, s]));
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {symbols.map((s) => (
          <span key={s} className="inline-flex max-w-full items-center gap-1 rounded-full border border-line-strong bg-surface py-0.5 pl-3 pr-1 text-sm">
            <span className="truncate font-medium">{s}</span>
            {names[s] && <span className="hidden truncate text-xs text-muted sm:inline">{names[s]}</span>}
            <Link
              href={href(symbols.filter((x) => x !== s))}
              aria-label={`Remove ${s}`}
              className="ml-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
            >
              ×
            </Link>
          </span>
        ))}
        {!full && (
          <StockSearch
            className="w-full sm:w-72"
            placeholder={symbols.length ? "Add another: name or symbol" : "Add a stock: tata steel, RIL, INFY"}
            onPick={add}
            autoFocus={symbols.length > 0 && symbols.length < 2}
          />
        )}
        {symbols.length > 1 && (
          <Link href="/stocks/compare" className="text-sm text-muted underline">
            Clear
          </Link>
        )}
      </div>
      <p className="text-xs text-muted">
        {full
          ? `${MAX_COMPARE} is the most side by side. Remove one to add another.`
          : `Up to ${MAX_COMPARE} stocks. Pick from the suggestions, or press Enter to add what you typed.`}
      </p>
    </div>
  );
}
