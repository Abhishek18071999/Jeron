// The trade picture (docs/plans/ui-v2.md): where the price sits between the stop and the
// targets, as a ruler from -1R to +3R. 1R is the distance from entry to the initial stop.
import { inr } from "./ui";

const MIN_R = -1;
const MAX_R = 3;

const at = (r: number) => `${((Math.min(MAX_R, Math.max(MIN_R, r)) - MIN_R) / (MAX_R - MIN_R)) * 100}%`;

export function RRuler({
  entry,
  stop,
  price,
  t1,
  t2,
  priceLabel = "Last close",
}: {
  entry: number | string | null;
  stop: number | string | null;
  price: number | string | null;
  t1?: number | string | null;
  t2?: number | string | null;
  priceLabel?: string;
}) {
  const e = Number(entry);
  const s = Number(stop);
  const risk = e - s;
  if (!entry || !stop || !(risk > 0)) return null;
  const r = (v: number | string | null | undefined) => (v === null || v === undefined || v === "" ? null : (Number(v) - e) / risk);
  const now = r(price);
  const marks = [
    { r: -1, label: "Stop", value: s, tone: "bg-bad" },
    { r: 0, label: "Entry", value: e, tone: "bg-fg/60" },
    ...(r(t1) !== null ? [{ r: r(t1) as number, label: "T1", value: Number(t1), tone: "bg-good" }] : []),
    ...(r(t2) !== null ? [{ r: r(t2) as number, label: "T2", value: Number(t2), tone: "bg-good" }] : []),
  ];
  return (
    <figure className="w-full" aria-label="Where the price is between the stop and the targets">
      <div className="relative mt-5 h-2 rounded-full bg-gradient-to-r from-bad-bg via-surface-2 to-good-bg">
        {marks.map((m) => (
          <div key={m.label} className="absolute top-[-4px] flex -translate-x-1/2 flex-col items-center" style={{ left: at(m.r) }}>
            <span className={`h-4 w-0.5 ${m.tone}`} />
            <span className="mt-1 whitespace-nowrap text-[0.65rem] text-muted" title={inr(m.value)}>
              {m.label}
            </span>
          </div>
        ))}
        {now !== null && (
          <div className="absolute -top-5 flex -translate-x-1/2 flex-col items-center" style={{ left: at(now) }}>
            <span className={`whitespace-nowrap text-[0.7rem] font-semibold ${now >= 0 ? "text-good" : "text-bad"}`}>
              {now > 0 ? "+" : ""}
              {now.toFixed(1)}R
            </span>
            <span className="h-0 w-0 border-x-4 border-t-[6px] border-x-transparent border-t-fg" />
          </div>
        )}
      </div>
      <figcaption className="mt-6 text-xs text-muted">
        {now !== null && (
          <>
            {priceLabel} {inr(price)} is {now >= 0 ? "+" : ""}
            {now.toFixed(2)}R.{" "}
          </>
        )}
        1R = {inr(risk)} a share (entry {inr(e)} to stop {inr(s)}).
        {now !== null && (now < MIN_R || now > MAX_R) ? " Off the ruler's -1R to +3R range." : ""}
      </figcaption>
    </figure>
  );
}
