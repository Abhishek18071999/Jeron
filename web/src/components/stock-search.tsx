"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

type Match = { symbol: string; name: string | null; series: string; alias: string | null };

type Props = {
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  // Form field mode: the input carries this name and picking a suggestion fills in the
  // symbol. Without it, picking opens the stock page.
  name?: string;
  defaultValue?: string;
  required?: boolean;
};

// Type a symbol, a company name ("tata steel"), a short name ("RIL") or an old symbol
// ("ZOMATO"); suggestions appear as you type.
export function StockSearch({
  className = "",
  inputClassName = "w-full rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-sm placeholder:text-muted",
  placeholder = "Search: tata steel, RIL",
  name,
  defaultValue = "",
  required,
}: Props) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState(defaultValue);
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
    setMatches([]);
    if (name) {
      setQuery(symbol);
      return;
    }
    setQuery("");
    router.push(`/stocks/${encodeURIComponent(symbol)}`);
  };

  const shown = open && query.trim() ? matches : [];

  return (
    <div ref={box} className={`relative ${className}`}>
      <input
        name={name}
        required={required}
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
            // In a form, Enter with no suggestion showing submits the form as usual.
            if (name && !shown[active]) return;
            e.preventDefault();
            const pick = shown[active]?.symbol ?? query.trim().toUpperCase().replace(/\s+/g, "");
            if (pick) go(pick);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        placeholder={placeholder}
        aria-label={placeholder}
        role="combobox"
        aria-expanded={shown.length > 0}
        aria-controls={listId}
        autoComplete="off"
        className={inputClassName}
      />
      {shown.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute right-0 left-0 z-50 mt-1 max-h-80 overflow-auto rounded-lg border border-line bg-surface text-sm shadow-lg"
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
              className={`cursor-pointer px-3 py-2 ${i === active ? "bg-surface-2" : ""}`}
            >
              <span className="font-medium">{m.symbol}</span>
              {m.series !== "EQ" && <span className="ml-1 text-xs text-muted">{m.series}</span>}
              {m.alias && <span className="ml-2 text-xs text-muted">{m.alias}</span>}
              {m.name && <span className="block truncate text-xs text-muted">{m.name}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
