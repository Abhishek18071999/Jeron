"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

type Match = { symbol: string; name: string | null; series: string };

// Type a symbol or a company name ("tata steel"); suggestions appear as you type.
export function StockSearch({ className = "" }: { className?: string }) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal: controller.signal });
        setMatches(res.ok ? ((await res.json()) as Match[]) : []);
        setActive(0);
      } catch {
        // A newer keystroke aborted this request.
      }
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (symbol: string) => {
    setOpen(false);
    setQuery("");
    setMatches([]);
    router.push(`/stocks/${encodeURIComponent(symbol)}`);
  };

  const shown = query.trim() ? matches : [];

  return (
    <div ref={box} className={`relative ${className}`}>
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          if (!e.target.value.trim()) setMatches([]);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((i) => Math.min(i + 1, shown.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const pick = shown[active]?.symbol ?? query.trim().toUpperCase().replace(/\s+/g, "");
            if (pick) go(pick);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        placeholder="Search a stock, e.g. tata steel"
        aria-label="Search a stock"
        role="combobox"
        aria-expanded={open && shown.length > 0}
        aria-controls={listId}
        autoComplete="off"
        className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
      />
      {open && shown.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute right-0 left-0 z-20 mt-1 max-h-80 overflow-auto rounded border border-neutral-200 bg-white text-sm shadow-lg dark:border-neutral-700 dark:bg-neutral-900"
        >
          {shown.map((m, i) => (
            <li
              key={m.symbol}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                go(m.symbol);
              }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-2 ${i === active ? "bg-neutral-100 dark:bg-neutral-800" : ""}`}
            >
              <span className="font-medium">{m.symbol}</span>
              {m.series !== "EQ" && <span className="ml-1 text-xs text-neutral-500">{m.series}</span>}
              {m.name && <span className="block truncate text-xs text-neutral-500">{m.name}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
