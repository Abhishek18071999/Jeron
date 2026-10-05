import { apiUrl } from "@/lib/api";

// Same-origin proxy for the trade plan form's live numbers (read only), so the browser
// never calls the backend itself. Saving goes through a server action.
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const symbol = (params.get("symbol") ?? "").trim().toUpperCase();
  if (!/^[A-Z0-9&_.-]{1,32}$/.test(symbol)) return Response.json({ detail: "Unknown stock" }, { status: 400 });
  const query = new URLSearchParams();
  for (const key of ["entry", "stop", "tier", "signal_id"]) {
    const value = params.get(key)?.trim();
    if (value) query.set(key, value);
  }
  try {
    const res = await fetch(`${apiUrl()}/plan/${encodeURIComponent(symbol)}?${query}`, { cache: "no-store" });
    const body = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    return Response.json(body, { status: res.status });
  } catch {
    return Response.json({ detail: "The backend is not reachable" }, { status: 502 });
  }
}
