import { fetchHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <li className="flex items-center justify-between rounded-lg border border-neutral-200 px-4 py-3 dark:border-neutral-800">
      <span>{label}</span>
      <span className={ok ? "text-green-600" : "text-red-600"}>{detail}</span>
    </li>
  );
}

export default async function Home() {
  const health = await fetchHealth();

  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <h1 className="text-3xl font-semibold">Jeron</h1>
      <p className="mt-2 text-neutral-500">
        Research and decision support for Indian equities. Signals arrive in later
        milestones; this page confirms the system is running.
      </p>
      <ul className="mt-8 space-y-3">
        <StatusRow
          label="Backend API"
          ok={health !== null}
          detail={health ? "running" : "not reachable"}
        />
        <StatusRow
          label="Database"
          ok={health?.database === "ok"}
          detail={health?.database === "ok" ? "connected" : "not connected"}
        />
      </ul>
    </main>
  );
}
