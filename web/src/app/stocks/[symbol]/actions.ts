"use server";

import { type ApiResult, type Narration, sendJson } from "@/lib/api";

// The LLM's wording of the brief, checked by the backend; the browser never calls the API.
export async function narrateStock(
  symbol: string,
  _previous: ApiResult<Narration> | null,
  form: FormData,
): Promise<ApiResult<Narration>> {
  const question = String(form.get("question") ?? "").trim().slice(0, 300);
  return sendJson<Narration>("POST", `/stocks/${encodeURIComponent(symbol)}/explain/narrate`, {
    question: question || null,
  });
}
