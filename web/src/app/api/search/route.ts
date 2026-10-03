import { apiUrl } from "@/lib/api";

// Same-origin proxy for the search box, so the browser never calls the backend itself.
export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q")?.trim() ?? "";
  if (!q) return Response.json([]);
  try {
    const res = await fetch(`${apiUrl()}/stocks/search?${new URLSearchParams({ q, limit: "8" })}`, {
      cache: "no-store",
    });
    return Response.json(res.ok ? await res.json() : []);
  } catch {
    return Response.json([]);
  }
}
