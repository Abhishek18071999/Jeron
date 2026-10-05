import type { QualityStatus } from "@/lib/api";

import { Badge, type Tone } from "./ui";

const tones: Record<QualityStatus, Tone> = { pass: "neutral", warn: "warn", fail: "bad" };

export function StatusBadge({ status }: { status: QualityStatus }) {
  return <Badge tone={tones[status]}>{status}</Badge>;
}
