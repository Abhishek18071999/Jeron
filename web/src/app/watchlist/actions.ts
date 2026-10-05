"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type Watchlist, sendJson } from "@/lib/api";

const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();

function refresh(ticker?: string) {
  revalidatePath("/watchlist");
  revalidatePath("/");
  revalidatePath("/stocks");
  if (ticker) revalidatePath(`/stocks/${ticker}`);
}

// Add a stock, or change its alert price and note. `back` is where to return.
export async function saveWatch(form: FormData) {
  const ticker = text(form, "ticker").toUpperCase().replace(/\s+/g, "");
  const price = text(form, "alert_price");
  const back = text(form, "back") || "/watchlist";
  const result = await sendJson<Watchlist>("POST", "/watchlist", {
    ticker,
    alert_price: price || null,
    alert_direction: price ? text(form, "alert_direction") || "above" : null,
    note: text(form, "note"),
  });
  if (!result.ok) redirect(`${back}${back.includes("?") ? "&" : "?"}error=${encodeURIComponent(result.error)}`);
  refresh(ticker);
  redirect(back);
}

export async function removeWatch(ticker: string, back: string) {
  await sendJson<Watchlist>("DELETE", `/watchlist/${encodeURIComponent(ticker)}`);
  refresh(ticker);
  redirect(back);
}
