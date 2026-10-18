import Link from "next/link";

import { Page, PageHeader } from "@/components/ui";
import { GLOSSARY, lessonBySlug } from "@/lib/lessons";

export const metadata = { title: "Glossary · Learn · Jeron" };

export default function GlossaryPage() {
  const terms = [...GLOSSARY].sort((a, b) => a.term.localeCompare(b.term));
  const letters = [...new Set(terms.map((t) => t.term[0].toUpperCase()))];
  return (
    <Page width="narrow">
      <nav className="text-sm text-muted">
        <Link href="/learn" className="hover:underline">
          Learn
        </Link>{" "}
        · Glossary
      </nav>
      <PageHeader title="Glossary" subtitle="Every term the lessons use, in one line, with the lesson that explains it properly." />
      <nav className="flex flex-wrap gap-1.5 text-sm" aria-label="Letters">
        {letters.map((l) => (
          <a key={l} href={`#${l}`} className="rounded-md border border-line px-2 py-0.5 hover:bg-surface-2">
            {l}
          </a>
        ))}
      </nav>
      {letters.map((letter) => (
        <section key={letter} id={letter} className="scroll-mt-20 space-y-2">
          <h2 className="text-lg font-semibold">{letter}</h2>
          <dl className="divide-y divide-line rounded-xl border border-line bg-surface">
            {terms
              .filter((t) => t.term[0].toUpperCase() === letter)
              .map((t) => {
                const lesson = t.lesson ? lessonBySlug(t.lesson) : undefined;
                return (
                  <div key={t.term} className="px-4 py-3">
                    <dt className="font-semibold">{t.term}</dt>
                    <dd className="mt-0.5 text-sm text-muted">
                      {t.meaning}
                      {lesson && (
                        <>
                          {" "}
                          <Link href={`/learn/${lesson.slug}`} className="font-medium text-accent hover:underline">
                            Lesson: {lesson.title} →
                          </Link>
                        </>
                      )}
                    </dd>
                  </div>
                );
              })}
          </dl>
        </section>
      ))}
    </Page>
  );
}
