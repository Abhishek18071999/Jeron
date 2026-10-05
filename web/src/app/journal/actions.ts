"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type JournalEntry, type TradebookImport, sendJson } from "@/lib/api";

const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();
const optional = (form: FormData, name: string) => text(form, name) || null;

function plan(form: FormData) {
  const followed = text(form, "followed_plan");
  return {
    decision: text(form, "decision"),
    reason: text(form, "reason"),
    stop: optional(form, "stop"),
    followed_plan: followed === "yes" ? true : followed === "no" ? false : null,
    notes: text(form, "notes"),
    plan_id: planId(form),
  };
}

function planId(form: FormData) {
  const id = Number(text(form, "plan_id"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

function fail(path: string, error: string): never {
  redirect(`${path}?error=${encodeURIComponent(error)}`);
}

function done(entry: JournalEntry): never {
  revalidatePath("/journal");
  revalidatePath("/");
  redirect(`/journal/${entry.id}`);
}

export async function decideSignal(signalId: string, form: FormData) {
  const result = await sendJson<JournalEntry>("PUT", `/journal/signal/${signalId}`, plan(form));
  if (!result.ok) fail(`/journal/signal/${signalId}`, result.error);
  done(result.data);
}

export async function updateEntry(entryId: number, form: FormData) {
  const result = await sendJson<JournalEntry>("PUT", `/journal/${entryId}`, plan(form));
  if (!result.ok) fail(`/journal/${entryId}`, result.error);
  done(result.data);
}

export async function addFill(entryId: number, form: FormData) {
  const result = await sendJson<JournalEntry>("POST", `/journal/${entryId}/fills`, {
    trade_date: text(form, "trade_date"),
    side: text(form, "side"),
    shares: Number(text(form, "shares")),
    price: text(form, "price"),
    charges: text(form, "charges") || "0",
  });
  if (!result.ok) fail(`/journal/${entryId}`, result.error);
  done(result.data);
}

export async function deleteFill(entryId: number, fillId: number) {
  const result = await sendJson<JournalEntry>("DELETE", `/journal/fills/${fillId}`);
  if (!result.ok) fail(`/journal/${entryId}`, result.error);
  done(result.data);
}

export async function addManual(form: FormData) {
  const result = await sendJson<JournalEntry>("POST", "/journal", {
    ticker: text(form, "ticker"),
    reason: text(form, "reason"),
    stop: optional(form, "stop"),
    notes: text(form, "notes"),
    plan_id: planId(form),
  });
  if (!result.ok) fail("/journal", result.error);
  done(result.data);
}

export async function importTradebook(form: FormData) {
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) fail("/journal", "Choose the tradebook CSV first");
  const result = await sendJson<TradebookImport>("POST", "/journal/import", { csv: await file.text() });
  if (!result.ok) fail("/journal", result.error);
  const r = result.data;
  const skipped = Object.entries(r.skipped).map(([segment, n]) => `${n} ${segment}`);
  const parts = [
    `${r.added} fills added (${r.to_signals} to signals, ${r.new_entries} new entries without a signal)`,
    `${r.already} already imported`,
    ...(skipped.length ? [`skipped ${skipped.join(", ")} (only equity cash is journalled)`] : []),
  ];
  revalidatePath("/journal");
  revalidatePath("/");
  const query = new URLSearchParams({ imported: parts.join("; ") });
  for (const p of r.problems) query.append("error", p);
  redirect(`/journal?${query}`);
}
