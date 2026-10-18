"use client";

// Tap a number to see what it means and how it was worked out (docs/plans/ui-v2.md).
// A bottom sheet on phones, a small panel on desktop. Replaces the 14px "?" icons.
import { useEffect, useId, useState } from "react";

export function Explain({
  title,
  text,
  how,
  children,
  className = "",
}: {
  title: React.ReactNode;
  text: string;
  how?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-controls={id}
        title={text}
        className={`cursor-help text-left underline decoration-line-strong decoration-dotted underline-offset-4 ${className}`}
      >
        {children}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="presentation">
          <button
            type="button"
            aria-label="Close"
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
          />
          <div
            id={id}
            role="dialog"
            aria-modal="true"
            className="sheet-in relative w-full max-w-md rounded-t-2xl border border-line bg-surface p-5 pb-8 text-sm shadow-xl sm:rounded-2xl sm:pb-5"
          >
            <div className="flex items-start justify-between gap-4">
              <h2 className="font-semibold">{title}</h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="-m-2 rounded-lg p-2 text-muted hover:text-fg"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <p className="mt-2">{text}</p>
            {how && (
              <>
                <p className="mt-3 text-xs font-medium text-muted">How Jeron works it out</p>
                <p className="mt-0.5 text-muted">{how}</p>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

// A terminal command with a copy button. Hidden on phones, which can't run it.
export function Command({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="hidden items-center gap-1.5 sm:inline-flex">
      <code>{command}</code>
      <button
        type="button"
        className="rounded border border-line-strong px-1.5 text-[0.7rem] text-muted hover:text-fg"
        onClick={() => {
          navigator.clipboard?.writeText(command).then(
            () => setCopied(true),
            () => setCopied(false),
          );
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
