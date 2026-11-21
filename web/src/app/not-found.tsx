// Shown for an address Jeron has nothing at: a mistyped page, or a stock, backtest,
// paper account or journal entry the backend answered 404 for (`isNotFound` in
// src/lib/api.ts). It answers 404 and offers the ways back.
import { LinkButton, Page, PageHeader } from "@/components/ui";

export default function NotFound() {
  return (
    <Page width="narrow">
      <PageHeader
        title="Not found"
        subtitle="Nothing is stored at this address. A stock may trade under a new symbol, or a link may point at a run or entry that was never saved."
      />
      <p className="text-muted">
        Search for a stock by its name or an old symbol with the search box at the top (Ctrl K), or go back to a list.
      </p>
      <div className="mt-6 flex flex-wrap gap-2">
        <LinkButton href="/" variant="primary">
          Today
        </LinkButton>
        <LinkButton href="/stocks">Stocks</LinkButton>
        <LinkButton href="/backtests">Backtests</LinkButton>
        <LinkButton href="/paper">Paper trading</LinkButton>
        <LinkButton href="/journal">Journal</LinkButton>
      </div>
    </Page>
  );
}
