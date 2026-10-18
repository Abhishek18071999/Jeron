import Link from "next/link";

import { Badge, Card, ErrorNote, Notice, Page, PageHeader, Table, Td, Th, type Tone, buttonClass, shortDate } from "@/components/ui";
import { type SetupStep, type SetupView, getJson } from "@/lib/api";

import { uploadFiles } from "./actions";

export const dynamic = "force-dynamic";

const STATE: Record<SetupStep["state"], { tone: Tone; text: string }> = {
  done: { tone: "good", text: "done" },
  working: { tone: "accent", text: "working on it" },
  waiting: { tone: "neutral", text: "starts by itself" },
  you: { tone: "warn", text: "needs you" },
};

function Log({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-2 text-xs text-muted">
      {lines.join("\n")}
    </pre>
  );
}

function StepCard({ step }: { step: SetupStep }) {
  const state = STATE[step.state];
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{step.title}</span>
        <Badge tone={state.tone}>{state.text}</Badge>
      </p>
      <p className="mt-1 text-sm text-muted">{step.detail}</p>
      {step.todo.length > 0 && (
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          {step.todo.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ol>
      )}
    </li>
  );
}

export default async function SetupPage({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string; error?: string | string[] }>;
}) {
  const { saved, error } = await searchParams;
  const result = await getJson<SetupView>("/setup");
  if (!result.ok) {
    return (
      <Page width="narrow">
        <PageHeader title="Setup" />
        <Notice tone="bad">
          {result.error}. Start Jeron with <code>docker compose up -d</code> in the Jeron folder.
        </Notice>
      </Page>
    );
  }
  const v = result.data;
  const needYou = v.steps.filter((s) => s.state === "you");
  const { now, last } = v.autopilot;
  const imports = v.imports;

  return (
    <Page width="narrow">
      <PageHeader
        title="Setup"
        subtitle="Jeron sets itself up while it runs: price history, news, quarterly results and backtests. This page shows what it has, what it's doing and the few things only you can do."
      />
      {needYou.length > 0 ? (
        <Notice tone="warn">
          {needYou.length === 1 ? "One thing needs you" : `${needYou.length} things need you`}:{" "}
          {needYou.map((s) => s.title.toLowerCase()).join(", ")}. Everything else runs by itself.
        </Notice>
      ) : (
        <Notice tone="good">Nothing needs you. Jeron keeps itself up to date while it runs.</Notice>
      )}

      <ul className="space-y-3">
        {v.steps.map((s) => (
          <StepCard key={s.key} step={s} />
        ))}
      </ul>

      <Card
        title="What Jeron is doing now"
        subtitle="Checked every minute while the scheduler runs. Long steps carry on after a restart."
      >
        {now ? (
          <>
            <p className="text-sm">
              <span className="font-medium">{now.why}</span>
              {now.since && <span className="text-muted"> Since {now.since.slice(11, 16)}.</span>}
            </p>
            <Log lines={now.log} />
          </>
        ) : (
          <p className="text-sm text-muted">Nothing running.</p>
        )}
        {last && (
          <div className="mt-3 border-t border-line pt-3 text-sm">
            <p className="text-muted">
              Last finished: {last.why} {last.code === 0 ? "It went fine." : `It ended with problems (code ${last.code}).`}
            </p>
            <Log lines={last.log} />
          </div>
        )}
      </Card>

      <Card
        title="Add files"
        subtitle="Quarterly results, bulk/block deals, insider trades, board meetings, the ASM list or a Zerodha tradebook, saved from nseindia.com or Kite. A .zip of them works too."
      >
        <ErrorNote error={error} />
        {saved && <Notice tone="good">Saved {saved}. Jeron starts importing within a minute.</Notice>}
        <form action={uploadFiles} className="mt-2 flex flex-wrap items-center gap-3">
          <input name="files" type="file" multiple accept=".csv,.json,.zip,text/csv" required className="min-w-0 text-sm" />
          <button className={buttonClass}>Upload</button>
        </form>
        <p className="mt-2 text-xs text-muted">
          Or copy them into the <code>imports</code> folder inside your Jeron folder (for example{" "}
          <code>C:\Users\you\Jeron\imports</code>). Jeron recognises each file by its columns, and moves it to{" "}
          <code>imports\done</code> or <code>imports\failed</code> with a note saying what happened.
        </p>
        {(imports.running || imports.pending.length > 0) && (
          <div className="mt-3 border-t border-line pt-3 text-sm">
            {imports.running && (
              <>
                <p>
                  Importing <span className="font-medium">{imports.running.file}</span> ({imports.running.kind})
                </p>
                <Log lines={imports.running.log} />
              </>
            )}
            {imports.pending.length > 0 && (
              <p className="mt-2 text-muted">Waiting: {imports.pending.join(", ")}</p>
            )}
          </div>
        )}
        {imports.finished.length > 0 && (
          <ul className="mt-3 space-y-2 border-t border-line pt-3 text-sm">
            {imports.finished.map((f) => (
              <li key={`${f.file}-${f.at}`}>
                <p className="flex flex-wrap items-center gap-2">
                  <Badge tone={f.outcome === "done" ? "good" : "bad"}>{f.outcome === "done" ? "imported" : "failed"}</Badge>
                  <span className="font-medium">{f.file}</span>
                  <span className="text-xs text-muted">{shortDate(f.at.slice(0, 10))}</span>
                </p>
                {f.log.length > 0 && <p className="mt-0.5 text-xs text-muted">{f.log[f.log.length - 1]}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="Strategies"
        subtitle="Each is backtested by itself. Only those that passed the out-of-sample bar give live signals; the rest are research only."
        action={
          <Link href="/backtests" className="underline">
            Report cards
          </Link>
        }
      >
        <Table>
          <thead>
            <tr>
              <Th>Strategy</Th>
              <Th>Backtest</Th>
              <Th>Paper</Th>
            </tr>
          </thead>
          <tbody>
            {v.strategies.map((s) => (
              <tr key={s.key}>
                <Td>
                  <span className="font-medium">{s.version}</span>
                  <span className="block text-xs text-muted">{s.name}</span>
                </Td>
                <Td>
                  {s.tested === null ? (
                    <Badge>not yet</Badge>
                  ) : s.live_eligible ? (
                    <Badge tone="good">passed</Badge>
                  ) : (
                    <Badge tone="warn">research only</Badge>
                  )}
                </Td>
                <Td>{s.paper ? "trading" : "-"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </Page>
  );
}
