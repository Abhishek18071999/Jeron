import { redirect } from "next/navigation";

export default async function Stocks({ searchParams }: { searchParams: Promise<{ symbol?: string }> }) {
  const { symbol } = await searchParams;
  const clean = (symbol ?? "").trim().toUpperCase();
  redirect(clean ? `/stocks/${encodeURIComponent(clean)}` : "/scanner");
}
