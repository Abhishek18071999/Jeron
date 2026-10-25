"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import {
  SESSION_COOKIE,
  SESSION_DAYS,
  lockedFor,
  loginConfig,
  newSession,
  recordFailure,
  recordSuccess,
  safeNext,
  verifyPassword,
  verifyTotp,
} from "@/lib/auth";

function fail(next: string, error: string): never {
  const params = new URLSearchParams({ error });
  if (next !== "/") params.set("next", next);
  redirect(`/login?${params}`);
}

export async function login(form: FormData) {
  const next = safeNext(String(form.get("next") ?? "/"));
  const config = loginConfig();
  if (config.mode !== "on") redirect("/login");
  const wait = lockedFor();
  if (wait > 0) fail(next, `Too many wrong tries. Try again in ${Math.ceil(wait / 60000)} minutes.`);
  const passwordOk = verifyPassword(String(form.get("password") ?? ""), config.passwordHash);
  const codeOk = passwordOk && verifyTotp(config.totpSecret, String(form.get("code") ?? ""));
  if (!codeOk) {
    recordFailure();
    fail(next, "The password or the code is wrong.");
  }
  recordSuccess();
  const proto = (await headers()).get("x-forwarded-proto");
  (await cookies()).set(SESSION_COOKIE, newSession(config), {
    httpOnly: true,
    sameSite: "lax",
    // Secure only over https: on the home network the phone opens Jeron over http.
    secure: proto === "https",
    path: "/",
    maxAge: SESSION_DAYS * 24 * 3600,
  });
  redirect(next);
}

export async function logout() {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
