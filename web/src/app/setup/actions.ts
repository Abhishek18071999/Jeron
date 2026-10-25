"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiHeaders, apiUrl } from "@/lib/api";

// Uploads go into the imports folder through the backend; the scheduler imports them.
export async function uploadFiles(form: FormData) {
  const files = form.getAll("files").filter((f): f is File => f instanceof File && f.size > 0);
  if (files.length === 0) redirect(`/setup?error=${encodeURIComponent("Choose a file first")}`);
  const saved: string[] = [];
  const errors: string[] = [];
  for (const file of files) {
    try {
      const res = await fetch(`${apiUrl()}/imports/${encodeURIComponent(file.name)}`, {
        method: "PUT",
        headers: apiHeaders({ "Content-Type": "application/octet-stream" }),
        body: Buffer.from(await file.arrayBuffer()),
        cache: "no-store",
      });
      if (res.ok) saved.push(file.name);
      else {
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        errors.push(typeof body?.detail === "string" ? body.detail : `${file.name}: HTTP ${res.status}`);
      }
    } catch {
      errors.push("The backend is not reachable");
    }
  }
  revalidatePath("/setup");
  const query = new URLSearchParams();
  if (saved.length) query.set("saved", saved.join(", "));
  for (const e of errors) query.append("error", e);
  redirect(`/setup?${query}`);
}
