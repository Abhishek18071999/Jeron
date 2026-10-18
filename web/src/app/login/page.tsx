import { redirect } from "next/navigation";

import { ErrorNote, buttonClass, RunCommand, inputClass } from "@/components/ui";
import { loginConfig } from "@/lib/auth";

import { login } from "./actions";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const config = loginConfig();
  if (config.mode === "off") redirect("/");
  const { error, next } = await searchParams;
  return (
    // Covers the header and tab bar: nothing behind the login is reachable anyway.
    <div className="fixed inset-0 z-50 overflow-y-auto bg-bg">
      <main className="mx-auto flex min-h-full max-w-sm flex-col justify-center px-4 py-10">
        <h1 className="mb-1 text-2xl font-semibold tracking-tight">Jeron</h1>
        {config.mode === "unset" ? (
          <div className="space-y-3 text-sm">
            <p className="text-muted">The login isn&apos;t set up yet, so Jeron stays locked.</p>
            <ol className="list-decimal space-y-2 pl-5">
              <li>
                <RunCommand job="auth-setup" phone="On your computer, run the auth-setup command" />, choose a password and add the account to your
                authenticator app.
              </li>
              <li>
                Put the two lines it prints into <code>.env</code>, then run{" "}
                <code>docker compose up -d</code>.
              </li>
            </ol>
          </div>
        ) : (
          <>
            <p className="mb-5 text-sm text-muted">Your password and the code from your authenticator app.</p>
            <ErrorNote error={error} />
            <form action={login} className="space-y-3">
              <input type="hidden" name="next" value={next ?? "/"} />
              <label className="block text-sm">
                <span className="mb-1 block font-medium">Password</span>
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  autoFocus
                  className={inputClass}
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">6-digit code</span>
                <input
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9 ]{6,7}"
                  maxLength={7}
                  required
                  className={inputClass}
                />
              </label>
              <button className={`${buttonClass} w-full py-2`}>Log in</button>
            </form>
          </>
        )}
      </main>
    </div>
  );
}
