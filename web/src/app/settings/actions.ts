"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type SettingsView, getJson, sendJson } from "@/lib/api";

function done(result: { ok: true } | { ok: false; error: string }): never {
  if (!result.ok) redirect(`/settings?error=${encodeURIComponent(result.error)}`);
  // Sizes, heat and limits on every page read these.
  revalidatePath("/", "layout");
  redirect("/settings?saved=1");
}

export async function saveSettings(form: FormData) {
  const current = await getJson<SettingsView>("/settings");
  if (!current.ok) done(current);
  const changes: Record<string, string | boolean> = {};
  for (const row of current.data.settings) {
    if (typeof row.value === "boolean") changes[row.key] = form.get(row.key) === "on";
    else changes[row.key] = String(form.get(row.key) ?? "").replace(/,/g, "").trim();
  }
  done(await sendJson<SettingsView>("PUT", "/settings", { changes }));
}

export async function resetSetting(key: string) {
  done(await sendJson<SettingsView>("PUT", "/settings", { changes: { [key]: null } }));
}
