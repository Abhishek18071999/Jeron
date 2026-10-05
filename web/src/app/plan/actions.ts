"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type SavedPlan, sendJson } from "@/lib/api";

const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();

// Saves a trade plan. The backend re-checks everything (size, section 4 checks, limits,
// the checklist) and refuses with the reasons; plans are never changed, only replaced.
export async function savePlan(symbol: string, form: FormData) {
  const signalId = text(form, "signal_id") || null;
  const back = (extra: Record<string, string>) => {
    const query = new URLSearchParams({
      ...(signalId ? { signal: signalId } : {}),
      entry: text(form, "entry"),
      stop: text(form, "stop"),
      tier: text(form, "tier"),
      ...extra,
    });
    return `/plan/${encodeURIComponent(symbol)}?${query}`;
  };
  const result = await sendJson<SavedPlan>("POST", "/plans", {
    ticker: symbol,
    tier: text(form, "tier") || "swing",
    entry: text(form, "entry"),
    stop: text(form, "stop"),
    reason: text(form, "reason"),
    signal_id: signalId,
    checklist: form.getAll("checklist").map(String),
  });
  if (!result.ok) redirect(back({ error: result.error }));
  revalidatePath(`/plan/${symbol}`);
  revalidatePath("/journal");
  redirect(back({ saved: String(result.data.id) }));
}
