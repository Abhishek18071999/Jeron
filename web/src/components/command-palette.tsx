"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Match = { symbol: string; name: string | null; series: string; alias: string | null };

type Item = {
  id: string;
  group: "Stocks" | "Commands" | "Pages";
  label: string;
  hint?: string;
  href: string;
};

const PAGES: { label: string; href: string; keywords?: string }[] = [
  { label: "Today", href: "/", keywords: "home dashboard actions signals" },
  { label: "Stocks", href: "/stocks", keywords: "heatmap sectors industries ranked list" },
  { label: "Watchlist", href: "/watchlist", keywords: "alerts star watch" },
  { label: "Portfolio", href: "/portfolio", keywords: "positions risk heat holdings" },
  { label: "Journal", href: "/journal", keywords: "trades fills record tradebook" },
  { label: "Research", href: "/research" },
  { label: "Scanner", href: "/scanner", keywords: "scan score" },
  { label: "Backtests", href: "/backtests", keywords: "strategies report cards" },
  { label: "Paper trading", href: "/paper", keywords: "paper accounts" },
  { label: "Compare", href: "/compare", keywords: "backtest paper real" },
  { label: "Data quality", href: "/data", keywords: "quality coverage" },
  { label: "Spot check", href: "/spot-check", keywords: "prices adjusted" },
];

// Subsequence match: every typed letter in order; earlier and tighter matches score
// higher. Null when it doesn't match.
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.toLowerCase().replace(/\s+/g, "");
  const t = text.toLowerCase();
  if (!q) return 0;
  if (t.startsWith(q)) return 1000 - t.length;
  const at = t.indexOf(q);
  if (at >= 0) return 800 - at;
  let score = 0;
  let last = -1;
  for (const ch of q) {
    const i = t.indexOf(ch, last + 1);
    if (i < 0) return null;
    score += i === last + 1 ? 5 : 1;
    last = i;
  }
  return score;
}

const PLAN = /^plan\s+(.*)$/i;

export function CommandPalette() {
  const router = useRouter();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  const show = useCallback(() => {
    opener.current = document.activeElement as HTMLElement | null;
    setQuery("");
    setMatches([]);
    setActive(0);
    setOpen(true);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    opener.current?.focus?.();
  }, []);

  // Ctrl+K / Cmd+K anywhere toggles it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) close();
        else show();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, show, close]);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
    };
  }, [open]);

  const planQuery = query.match(PLAN)?.[1]?.trim();
  const stockQuery = (planQuery ?? query).trim();

  useEffect(() => {
    if (!open || !stockQuery) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(stockQuery)}`, { signal: controller.signal });
        setMatches(res.ok ? ((await res.json()) as Match[]) : []);
        setActive(0);
      } catch {
        // A newer keystroke aborted this request.
      }
    }, 120);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [open, stockQuery]);

  const items = useMemo<Item[]>(() => {
    const stocks = stockQuery ? matches : [];
    const out: Item[] = [];
    if (planQuery !== undefined) {
      for (const m of stocks.slice(0, 8)) {
        out.push({ id: `plan-${m.symbol}`, group: "Commands", label: `Plan trade ${m.symbol}`, hint: m.name ?? undefined, href: `/plan/${encodeURIComponent(m.symbol)}` });
      }
      return out;
    }
    for (const m of stocks.slice(0, 6)) {
      out.push({
        id: `stock-${m.symbol}`,
        group: "Stocks",
        label: m.symbol,
        hint: [m.alias, m.name].filter(Boolean).join(" · ") || undefined,
        href: `/stocks/${encodeURIComponent(m.symbol)}`,
      });
    }
    for (const m of stocks.slice(0, 2)) {
      out.push({ id: `plan-${m.symbol}`, group: "Commands", label: `Plan trade ${m.symbol}`, hint: "size it, check it, tick the checklist", href: `/plan/${encodeURIComponent(m.symbol)}` });
    }
    if (!query.trim()) {
      out.push({ id: "cmd-plan", group: "Commands", label: "Plan trade…", hint: "type plan and a stock, e.g. plan tata steel", href: "" });
    }
    const pages = PAGES.map((p) => ({ p, score: fuzzyScore(query, p.label) ?? (p.keywords && query.trim() && p.keywords.includes(query.trim().toLowerCase()) ? 1 : null) }))
      .filter((x) => x.score !== null)
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    for (const { p } of pages) out.push({ id: `page-${p.href}`, group: "Pages", label: p.label, href: p.href });
    return out;
  }, [matches, planQuery, query, stockQuery]);

  const go = (item: Item | undefined) => {
    if (!item) return;
    if (!item.href) {
      setQuery("plan ");
      input.current?.focus();
      return;
    }
    setOpen(false);
    router.push(item.href);
  };

  const current = Math.min(active, Math.max(0, items.length - 1));

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((current + 1) % Math.max(1, items.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((current - 1 + items.length) % Math.max(1, items.length));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(items.length - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(items[current]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "Tab") {
      // Focus trap: the input is the only stop inside the dialog.
      e.preventDefault();
    }
  };

  useEffect(() => {
    document.getElementById(`${listId}-${current}`)?.scrollIntoView({ block: "nearest" });
  }, [current, listId]);

  let lastGroup = "";
  const dialog = open
    ? createPortal(
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-3 pt-[10vh] backdrop-blur-[2px]" onMouseDown={close}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette: search stocks and pages"
            onMouseDown={(e) => e.stopPropagation()}
            onKeyDown={onKeyDown}
            className="w-full max-w-xl overflow-hidden rounded-xl border border-line bg-surface shadow-2xl"
          >
            <div className="flex items-center gap-2 border-b border-line px-3">
              <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5 shrink-0 text-muted" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4" />
              </svg>
              <input
                ref={input}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                  if (!e.target.value.trim()) setMatches([]);
                }}
                placeholder="Stock, page or “plan tata steel”"
                role="combobox"
                aria-expanded={items.length > 0}
                aria-controls={listId}
                aria-activedescendant={items.length ? `${listId}-${current}` : undefined}
                aria-autocomplete="list"
                autoComplete="off"
                spellCheck={false}
                className="w-full bg-transparent py-3.5 text-base outline-none placeholder:text-muted focus-visible:outline-none"
              />
              <kbd className="hidden shrink-0 rounded border border-line-strong px-1.5 py-0.5 text-[0.65rem] text-muted sm:inline">Esc</kbd>
            </div>
            <ul id={listId} role="listbox" aria-label="Results" className="max-h-[min(60vh,26rem)] overflow-y-auto py-1.5">
              {items.length === 0 && (
                <li className="px-4 py-6 text-center text-sm text-muted">
                  {planQuery === "" ? "Type the stock to plan, e.g. plan RIL." : "No match. Try a symbol, a company name or a page."}
                </li>
              )}
              {items.map((item, i) => {
                const heading = item.group !== lastGroup ? item.group : null;
                lastGroup = item.group;
                return (
                  <li key={item.id} role="presentation">
                    {heading && <p className="px-4 pt-2 pb-1 text-[0.68rem] font-semibold tracking-wide text-muted uppercase">{heading}</p>}
                    <div
                      id={`${listId}-${i}`}
                      role="option"
                      aria-selected={i === current}
                      onMouseMove={() => setActive(i)}
                      onClick={() => go(item)}
                      className={`mx-1.5 flex cursor-pointer items-baseline gap-3 rounded-lg px-2.5 py-2 text-sm ${i === current ? "bg-accent-bg text-fg" : ""}`}
                    >
                      <span className={`shrink-0 ${item.group === "Stocks" ? "font-semibold" : "font-medium"}`}>{item.label}</span>
                      {item.hint && <span className="min-w-0 truncate text-xs text-muted">{item.hint}</span>}
                      {i === current && <span className="ml-auto shrink-0 text-xs text-muted">↵</span>}
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="flex gap-4 border-t border-line px-4 py-2 text-[0.7rem] text-muted">
              <span>↑↓ to move</span>
              <span>↵ to open</span>
              <span className="hidden sm:inline">Ctrl K to toggle</span>
            </p>
          </div>
        </div>,
        document.body,
      )
    : null;

  return (
    <>
      <button
        type="button"
        onClick={show}
        aria-label="Search stocks and pages (Ctrl+K)"
        aria-haspopup="dialog"
        className="ml-auto inline-flex items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-sm text-muted hover:text-fg md:ml-0"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4" />
        </svg>
        <span className="sm:hidden">Search</span>
        <kbd className="hidden font-sans text-xs sm:inline">Ctrl K</kbd>
      </button>
      {dialog}
    </>
  );
}
