// Server-side calls to the Jeron backend. JERON_API_URL is read at request time,
// so the same build works locally and inside Docker Compose.
export const apiUrl = () => process.env.JERON_API_URL ?? "http://localhost:8000";

export type Health = { status: "ok" | "degraded"; database: "ok" | "unreachable" };

export async function fetchHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${apiUrl()}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}
