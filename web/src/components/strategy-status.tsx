import { Badge, type Tone } from "@/components/ui";
import type { EvidenceRating, StrategyHealth, StrategyStatus } from "@/lib/api";

// A strategy's status (decision 0018): how far its evidence has got, never a promotion
// Jeron made on its own.
const statusTones: Record<StrategyStatus, Tone> = {
  research: "neutral",
  paper: "accent",
  "small capital": "warn",
  approved: "good",
  retired: "bad",
};

export function StrategyStatusBadge({ status, title }: { status: StrategyStatus; title?: string }) {
  return (
    <Badge tone={statusTones[status]} title={title}>
      {status}
    </Badge>
  );
}

const evidenceTones: Record<EvidenceRating, Tone> = {
  strong: "good",
  moderate: "accent",
  weak: "bad",
  insufficient: "neutral",
};

export function EvidenceBadge({ rating, title }: { rating: EvidenceRating | null | undefined; title?: string }) {
  if (!rating) {
    return (
      <Badge title={title ?? "This run was made before evidence ratings: backtest it again to rate it"}>
        evidence not rated
      </Badge>
    );
  }
  return (
    <Badge tone={evidenceTones[rating]} title={title}>
      evidence {rating}
    </Badge>
  );
}

const healthTones: Record<StrategyHealth["verdict"], string> = {
  "too early": "text-muted",
  "on track": "text-good",
  "ordinary variance": "text-fg",
  watch: "text-warn",
  deteriorating: "text-bad",
};

export function HealthText({ health }: { health: StrategyHealth | null }) {
  if (!health) return <span className="text-muted">No paper account</span>;
  return <span className={healthTones[health.verdict]}>{health.verdict}</span>;
}
