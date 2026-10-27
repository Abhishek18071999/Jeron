"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { StockSearch } from "@/components/stock-search";
import { MAX_COMPARE, STOCK_COLORS } from "@/lib/compare";

const href = (symbols: string[]) =>
  symbols.length ? `/stocks/compare?symbols=${encodeURIComponent(symbols.join(","))}` : "/stocks/compare";

// The stocks being compared, as chips, and the same search box as the header's: type a
// symbol, a company name, a short name or an old symbol and pick a suggestion.
export function ComparePicker({ symbols, names }: { symbols: string[]; names: Record<string, string | null> }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const go = (to: string) => startTransition(() => router.push(to));
  const full = symbols.length >= MAX_COMPARE;
  const add = (symbol: string) => {
    const s = symbol.trim();
    if (!s || symbols.some((x) => x.toUpperCase() === s.toUpperCase())) return;
    go(href([...symbols, s]));
  };

  return (
    <div className="space-y-2" aria-busy={pending}>
      <div className="flex flex-wrap items-center gap-2">
        {symbols.map((s, i) => (
          <span key={s} className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line-strong bg-surface py-0.5 pl-3 pr-1 text-sm">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: STOCK_COLORS[i % STOCK_COLORS.length] }} />
            <span className="truncate font-medium">{s}</span>
            {names[s] && <span className="hidden max-w-48 truncate text-xs text-muted sm:inline">{names[s]}</span>}
            <button
              type="button"
              onClick={() => go(href(symbols.filter((x) => x !== s)))}
              disabled={pending}
              aria-label={`Remove ${s}`}
              className="inline-flex h-7 w-7 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
            >
              ×
            </button>
          </span>
        ))}
        {!full && (
          <StockSearch
            className="w-full sm:w-72"
            placeholder={symbols.length ? "Add another: name or symbol" : "Add a stock: tata steel, RIL, INFY"}
            onPick={add}
            exclude={symbols}
            disabled={pending}
            autoFocus={symbols.length === 1}
          />
        )}
        {symbols.length > 1 && (
          <button type="button" onClick={() => go("/stocks/compare")} disabled={pending} className="text-sm text-muted underline">
            Clear
          </button>
        )}
      </div>
      <p className="text-xs text-muted" aria-live="polite">
        {pending
          ? "Building the comparison…"
          : full
            ? `${MAX_COMPARE} is the most side by side. Remove one to add another.`
            : `Up to ${MAX_COMPARE} stocks. Pick from the suggestions, or press Enter to add what you typed.`}
      </p>
    </div>
  );
}
