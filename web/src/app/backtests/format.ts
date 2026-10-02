export const pct = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | string | null | undefined, digits = 2) => {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(digits) : value;
  }
  return value.toFixed(digits);
};

export const rupees = (value: number | string | null | undefined) => {
  if (value === null || value === undefined) return "-";
  const n = typeof value === "string" ? Number(value) : value;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

export const signClass = (value: number | string) =>
  Number(value) > 0
    ? "text-green-700 dark:text-green-400"
    : Number(value) < 0
      ? "text-red-700 dark:text-red-400"
      : "";
