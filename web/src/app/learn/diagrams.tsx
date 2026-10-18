import type { DiagramName } from "@/lib/learn/types";

// Small drawings for the lessons. Colours are the theme's variables, so they work in
// light and dark mode.
const fg = "var(--fg)";
const muted = "var(--muted)";
const good = "var(--good)";
const bad = "var(--bad)";
const accent = "var(--accent)";
const line = "var(--line-strong)";

function Frame({ children, caption, height = 200 }: { children: React.ReactNode; caption: string; height?: number }) {
  return (
    <figure className="my-4">
      <svg viewBox={`0 0 400 ${height}`} role="img" aria-label={caption} className="w-full max-w-lg">
        {children}
      </svg>
      <figcaption className="mt-1 text-xs text-muted">{caption}</figcaption>
    </figure>
  );
}

const Label = ({ x, y, children, color = muted, anchor = "start" }: { x: number; y: number; children: React.ReactNode; color?: string; anchor?: "start" | "middle" | "end" }) => (
  <text x={x} y={y} fill={color} fontSize="11" textAnchor={anchor}>
    {children}
  </text>
);

function Candle() {
  return (
    <Frame caption="A green candle (close above open) and a red one (close below open).">
      <line x1="110" y1="20" x2="110" y2="180" stroke={good} strokeWidth="2" />
      <rect x="90" y="60" width="40" height="80" fill={good} rx="2" />
      <Label x={140} y={24}>High</Label>
      <Label x={140} y={64}>Close</Label>
      <Label x={140} y={142}>Open</Label>
      <Label x={140} y={182}>Low</Label>
      <Label x={20} y={104}>Body</Label>
      <Label x={20} y={40}>Wick</Label>
      <line x1="290" y1="30" x2="290" y2="170" stroke={bad} strokeWidth="2" />
      <rect x="270" y="50" width="40" height="70" fill={bad} rx="2" />
      <Label x={320} y={54}>Open</Label>
      <Label x={320} y={122}>Close</Label>
    </Frame>
  );
}

function TradePlan() {
  const rows: [number, string, string, string][] = [
    [30, "T2 +3R", "₹590", good],
    [65, "T1 +2R (sell half)", "₹560", good],
    [100, "+1R (stop to breakeven)", "₹530", muted],
    [135, "Entry", "₹500", accent],
    [170, "Stop −1R", "₹470", bad],
  ];
  return (
    <Frame caption="Entry ₹500, stop ₹470: 1R is ₹30 a share. Targets are measured in R.">
      {rows.map(([y, name, price, color]) => (
        <g key={name}>
          <line x1="20" y1={y} x2="190" y2={y} stroke={color} strokeWidth="2" strokeDasharray={color === muted ? "4 4" : undefined} />
          <Label x={198} y={y + 4} color={color}>
            {price} {name}
          </Label>
        </g>
      ))}
      <rect x="40" y="100" width="130" height="35" fill={good} opacity="0.12" />
      <rect x="40" y="135" width="130" height="35" fill={bad} opacity="0.12" />
    </Frame>
  );
}

// A rising price with a slow average under it.
function EmaTrend() {
  const price = "M10,160 L40,150 L60,155 L90,130 L110,138 L140,110 L160,118 L190,92 L210,100 L240,75 L260,84 L290,58 L310,66 L340,44 L390,30";
  const ema50 = "M10,168 C120,150 220,110 390,58";
  const ema200 = "M10,175 C140,168 260,140 390,105";
  return (
    <Frame caption="An uptrend: higher highs and higher lows, price above the 50-day EMA, the 50-day above the 200-day.">
      <path d={price} fill="none" stroke={fg} strokeWidth="2" />
      <path d={ema50} fill="none" stroke={accent} strokeWidth="2" />
      <path d={ema200} fill="none" stroke="#8b5cf6" strokeWidth="2" />
      <Label x={330} y={72} color={accent}>50-day EMA</Label>
      <Label x={300} y={130} color="#8b5cf6">200-day EMA</Label>
      <Label x={20} y={20}>Price</Label>
    </Frame>
  );
}

function Breakout() {
  return (
    <Frame caption="Resistance at the 52-week high; the breakout closes above it on heavy volume.">
      <line x1="10" y1="60" x2="390" y2="60" stroke={bad} strokeWidth="1.5" strokeDasharray="5 4" />
      <Label x={14} y={54} color={bad}>52-week high (resistance)</Label>
      <path d="M10,140 L50,70 L90,120 L140,64 L180,110 L230,66 L270,95 L310,62 L340,40 L390,25" fill="none" stroke={fg} strokeWidth="2" />
      {[20, 60, 100, 140, 180, 220, 260, 300].map((x) => (
        <rect key={x} x={x} y={180} width="18" height="12" fill={line} />
      ))}
      <rect x={336} y={156} width="18" height="36" fill={accent} />
      <Label x={330} y={150} color={accent}>2x volume</Label>
    </Frame>
  );
}

function Pullback() {
  return (
    <Frame caption="A dip in an uptrend: price touches the 20-day EMA and holds; RSI dips below 40 and turns back up." height={230}>
      <path d="M10,120 L60,95 L100,70 L140,90 L160,105 L180,98 L220,70 L270,50 L320,35 L390,25" fill="none" stroke={fg} strokeWidth="2" />
      <path d="M10,135 C100,105 200,90 390,50" fill="none" stroke={accent} strokeWidth="2" />
      <circle cx="160" cy="105" r="6" fill="none" stroke={good} strokeWidth="2" />
      <Label x={172} y={124} color={good}>touch and hold</Label>
      <Label x={330} y={68} color={accent}>20-day EMA</Label>
      <line x1="10" y1="190" x2="390" y2="190" stroke={line} strokeDasharray="4 4" />
      <Label x={14} y={186}>RSI 40</Label>
      <path d="M10,170 L60,165 L100,172 L140,196 L160,204 L185,186 L230,170 L300,168 L390,164" fill="none" stroke={muted} strokeWidth="1.5" />
      <Label x={196} y={216} color={muted}>RSI turns back above 40</Label>
    </Frame>
  );
}

function Drawdown() {
  const bars: [string, number][] = [["−10%", 11], ["−20%", 25], ["−30%", 43], ["−50%", 100]];
  return (
    <Frame caption="The gain needed to recover from a loss grows much faster than the loss.">
      {bars.map(([name, need], i) => {
        const x = 30 + i * 92;
        const h = need * 1.4;
        return (
          <g key={name}>
            <rect x={x} y={170 - h} width="48" height={h} fill={need >= 43 ? bad : accent} opacity="0.85" />
            <Label x={x + 24} y={165 - h} anchor="middle" color={fg}>
              +{need}%
            </Label>
            <Label x={x + 24} y={188} anchor="middle">
              lose {name.slice(1)}
            </Label>
          </g>
        );
      })}
    </Frame>
  );
}

// Entry, stop, then a gap down that opens below the stop.
function Gap() {
  const candles: [number, number, number, number, number][] = [
    // x, open, close, high, low (in svg y; smaller is higher)
    [40, 110, 95, 88, 116],
    [80, 96, 86, 80, 100],
    [120, 88, 92, 82, 98],
    [160, 92, 84, 78, 96],
  ];
  return (
    <Frame caption="Stop ₹470, but results came out overnight: the stock opens at ₹440 and the stop sells there, not at ₹470.">
      <line x1="10" y1="70" x2="390" y2="70" stroke={accent} strokeWidth="1.5" strokeDasharray="5 4" />
      <Label x={300} y={64} color={accent}>Entry ₹500</Label>
      <line x1="10" y1="120" x2="390" y2="120" stroke={bad} strokeWidth="1.5" strokeDasharray="5 4" />
      <Label x={300} y={114} color={bad}>Stop ₹470</Label>
      {candles.map(([x, o, c, h, l]) => (
        <g key={x}>
          <line x1={x + 9} y1={h} x2={x + 9} y2={l} stroke={c < o ? good : bad} strokeWidth="1.5" />
          <rect x={x} y={Math.min(o, c)} width="18" height={Math.max(Math.abs(o - c), 2)} fill={c < o ? good : bad} />
        </g>
      ))}
      <line x1="209" y1="150" x2="209" y2="182" stroke={bad} strokeWidth="1.5" />
      <rect x="200" y="155" width="18" height="22" fill={bad} />
      <rect x="182" y="98" width="54" height="52" fill={bad} opacity="0.08" />
      <Label x={244} y={150} color={bad}>gap: nothing traded</Label>
      <Label x={244} y={164} color={bad}>between ₹470 and ₹440</Label>
      <Label x={226} y={196} anchor="middle" color={fg}>opens ₹440</Label>
    </Frame>
  );
}

// After T1 the stop follows the highest close, 2 x ATR below, and never moves down.
function TrailingStop() {
  const price = "M10,170 L40,160 L70,150 L100,125 L130,132 L160,100 L190,88 L220,94 L250,70 L280,62 L310,74 L340,96 L370,104";
  const trail = "M160,140 L190,128 L220,128 L250,110 L280,102 L310,102 L340,102 L370,102";
  return (
    <Frame caption="After T1 the trailing stop (dashed) rises with each new highest close and never falls. A close below it sells the rest at the next open.">
      <line x1="10" y1="150" x2="390" y2="150" stroke={accent} strokeWidth="1" strokeDasharray="2 4" />
      <Label x={14} y={146} color={accent}>Entry</Label>
      <line x1="10" y1="104" x2="160" y2="104" stroke={good} strokeWidth="1" strokeDasharray="2 4" />
      <Label x={14} y={98} color={good}>T1 +2R: sell half</Label>
      <path d={price} fill="none" stroke={fg} strokeWidth="2" />
      <path d={trail} fill="none" stroke={bad} strokeWidth="2" strokeDasharray="6 4" />
      <circle cx="160" cy="100" r="5" fill="none" stroke={good} strokeWidth="2" />
      <circle cx="370" cy="104" r="5" fill="none" stroke={bad} strokeWidth="2" />
      <Label x={170} y={170} color={bad}>trail: 2 × ATR below the highest close</Label>
      <Label x={388} y={124} color={bad} anchor="end">close below: sell</Label>
    </Frame>
  );
}

// 20 trades of a 40% win-rate strategy: losses come in runs, the account still rises.
function Streak() {
  const trades = [-1, 2.5, -1, -1, 3, -1, -1, -1, -1, -1, -1, 2, 4, -1, 2.5, -1, 2, 2, -1, 2];
  let equity = 0;
  const points = trades.map((r, i) => {
    equity += r;
    return [30 + i * 18, 120 - equity * 8] as const;
  });
  const path = ["M12,120", ...points.map(([x, y]) => `L${x},${y}`)].join(" ");
  return (
    <Frame caption="20 trades at a 40% win rate: 8 wins, 12 losses, including 6 losses in a row. Still +8R overall." height={210}>
      <line x1="20" y1="120" x2="390" y2="120" stroke={line} strokeDasharray="4 4" />
      <Label x={392} y={124} anchor="end">0R</Label>
      <path d={path} fill="none" stroke={accent} strokeWidth="2" />
      {trades.map((r, i) => (
        <rect key={i} x={24 + i * 18} y={r > 0 ? 180 - r * 6 : 180} width="12" height={Math.abs(r) * 6} fill={r > 0 ? good : bad} opacity="0.85" />
      ))}
      <rect x="114" y="174" width="106" height="18" fill="none" stroke={bad} strokeDasharray="3 3" />
      <Label x={120} y={206} color={bad}>6 losses in a row</Label>
    </Frame>
  );
}

export function Diagram({ name }: { name: DiagramName }) {
  switch (name) {
    case "candle":
      return <Candle />;
    case "trade-plan":
      return <TradePlan />;
    case "ema-trend":
      return <EmaTrend />;
    case "breakout":
      return <Breakout />;
    case "pullback":
      return <Pullback />;
    case "drawdown":
      return <Drawdown />;
    case "gap":
      return <Gap />;
    case "trailing-stop":
      return <TrailingStop />;
    case "streak":
      return <Streak />;
    default:
      return null;
  }
}
