import { removeWatch, saveWatch } from "@/app/watchlist/actions";

const star = (filled: boolean) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
    <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
  </svg>
);

// Watch or unwatch a stock from its page. A form posting to a server action, so it works
// without JavaScript and the browser never calls the backend.
export function WatchStar({ ticker, watched, back }: { ticker: string; watched: boolean; back: string }) {
  const label = watched ? `Remove ${ticker} from the watchlist` : `Add ${ticker} to the watchlist`;
  return (
    <form action={watched ? removeWatch.bind(null, ticker, back) : saveWatch} className="inline-flex">
      {!watched && (
        <>
          <input type="hidden" name="ticker" value={ticker} />
          <input type="hidden" name="back" value={back} />
        </>
      )}
      <button
        type="submit"
        title={label}
        aria-label={label}
        aria-pressed={watched}
        className={`rounded-lg p-1 transition-colors hover:bg-surface-2 ${watched ? "text-fg" : "text-muted hover:text-fg"}`}
      >
        {star(watched)}
      </button>
    </form>
  );
}
