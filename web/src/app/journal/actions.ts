"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type JournalEntry, sendJson } from "@/lib/api";

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
  };
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
  });
  if (!result.ok) fail("/journal", result.error);
  done(result.data);
}
