import { Badge, Card, ErrorNote, Notice, Page, PageHeader, buttonClass, RunCommand, inputClass } from "@/components/ui";
import { type SettingRow, type SettingsView, getJson } from "@/lib/api";
import { loginConfig } from "@/lib/auth";

import { logout } from "../login/actions";
import { resetSetting, saveSettings } from "./actions";

export const dynamic = "force-dynamic";

const shown = (v: number | boolean) => (typeof v === "boolean" ? (v ? "on" : "off") : v.toLocaleString("en-IN"));

function Field({ row }: { row: SettingRow }) {
  const changed = row.changed_at !== null;
  const note = changed
    ? `Changed here ${new Date(row.changed_at!).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" })}; .env says ${shown(row.env_value)}.`
    : "From .env.";
  if (typeof row.value === "boolean") {
    return (
      <div className="py-3">
        <label className="flex items-start gap-2.5 text-sm">
          <input type="checkbox" name={row.key} defaultChecked={row.value} className="mt-0.5 h-4 w-4" />
          <span>
            <span className="font-medium">{row.label}</span>
            <span className="block text-xs text-muted">{row.help}</span>
          </span>
        </label>
        <Footnote row={row} note={note} />
      </div>
    );
  }
  return (
    <div className="py-3">
      <label className="block text-sm">
        <span className="font-medium">{row.label}</span>
        <span className="block text-xs text-muted">{row.help}</span>
        <input
          name={row.key}
          defaultValue={String(row.value)}
          inputMode="decimal"
          required
          className={`${inputClass} mt-1.5 max-w-48`}
        />
      </label>
      <Footnote row={row} note={note} />
    </div>
  );
}

function Footnote({ row, note }: { row: SettingRow; note: string }) {
  return (
    <p className="mt-1 text-xs text-muted">
      {note}{" "}
      {row.changed_at !== null && (
        <button formAction={resetSetting.bind(null, row.key)} formNoValidate className="underline hover:text-fg">
          Use .env
        </button>
      )}
    </p>
  );
}

const ready = (ok: boolean, yes = "Set up", no = "Not set up") => (
  <Badge tone={ok ? "good" : "neutral"}>{ok ? yes : no}</Badge>
);

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { error, saved } = await searchParams;
  const result = await getJson<SettingsView>("/settings");
  const login = loginConfig().mode;
  return (
    <Page width="narrow">
      <PageHeader
        title="Settings"
        subtitle="Risk limits and alerts. Keys and passwords stay in .env, never here."
        action={
          login === "on" ? (
            <form action={logout}>
              <button className="text-sm text-muted hover:text-fg hover:underline">Log out</button>
            </form>
          ) : undefined
        }
      />
      <ErrorNote error={error} />
      {saved && !error && <Notice tone="good">Saved. New plans, sizes and limits use these from now on.</Notice>}
      {!result.ok ? (
        <Notice tone="bad">{result.error}</Notice>
      ) : (
        <>
          <Card
            title="Risk and alerts"
            subtitle="Paper accounts keep the values they opened with, so their record stays comparable."
          >
            <form action={saveSettings} className="divide-y divide-line">
              {result.data.settings.map((row) => (
                <Field key={row.key} row={row} />
              ))}
              <div className="pt-3">
                <button className={buttonClass}>Save</button>
              </div>
            </form>
          </Card>
          <Card title="News labels this month">
            <Spend view={result.data} />
          </Card>
          <Card title="What is set up" subtitle="Change these in .env, then restart.">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted">Login</dt>
              <dd>{login === "on" ? ready(true, "Password and code") : <Badge tone="bad">Off</Badge>}</dd>
              <dt className="text-muted">Telegram</dt>
              <dd>{ready(result.data.setup.telegram)}</dd>
              <dt className="text-muted">Email backup</dt>
              <dd>{ready(result.data.setup.email)}</dd>
              <dt className="text-muted">News labeller</dt>
              <dd>
                {ready(result.data.setup.news_ready, "Key set", "No key")}{" "}
                <span className="text-muted">
                  {result.data.setup.news_provider}, {result.data.setup.news_model}
                </span>
              </dd>
            </dl>
            {!result.data.setup.telegram && (
              <p className="mt-3 text-xs text-muted">
                Telegram: <RunCommand job="telegram --setup" lead="" phone="set it up from your computer." />
              </p>
            )}
          </Card>
        </>
      )}
    </Page>
  );
}

function Spend({ view }: { view: SettingsView }) {
  const spent = Number(view.news_spend.spent_usd);
  const cap = Number(view.news_spend.cap_usd);
  const share = cap > 0 ? Math.min(spent / cap, 1) : 0;
  return (
    <div className="text-sm">
      <p>
        About <span className="font-semibold">US${spent.toFixed(2)}</span>
        {cap > 0 ? ` of the US$${cap.toFixed(2)} cap` : " (no cap)"} since{" "}
        {new Date(view.news_spend.since).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" })}.
      </p>
      {cap > 0 && (
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
          <div className={`h-full ${share >= 1 ? "bg-bad" : "bg-accent"}`} style={{ width: `${share * 100}%` }} />
        </div>
      )}
      <p className="mt-2 text-xs text-muted">
        Estimated at list prices; your provider&apos;s bill is final. Models without a list price here
        (Ollama Cloud) aren&apos;t counted.
      </p>
    </div>
  );
}
