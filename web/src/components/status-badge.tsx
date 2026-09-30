import type { QualityStatus } from "@/lib/api";

const styles: Record<QualityStatus, string> = {
  pass: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  warn: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  fail: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

export function StatusBadge({ status }: { status: QualityStatus }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${styles[status]}`}>
      {status}
    </span>
  );
}
