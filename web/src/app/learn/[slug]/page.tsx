import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, Notice, Page, Table, Td, Th } from "@/components/ui";
import { type Block, LESSONS, TRACKS, lessonBySlug } from "@/lib/lessons";

import { Diagram } from "../diagrams";
import { MarkRead, Quiz } from "../quiz";
import { Rich } from "../rich";

export function generateStaticParams() {
  return LESSONS.map((l) => ({ slug: l.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const lesson = lessonBySlug((await params).slug);
  return { title: lesson ? `${lesson.title} · Learn · Jeron` : "Learn · Jeron" };
}

function BlockView({ block }: { block: Block }) {
  if ("p" in block) return <p className="leading-7"><Rich text={block.p} /></p>;
  if ("h" in block) return <h2 className="pt-2 text-lg font-semibold tracking-tight">{block.h}</h2>;
  if ("list" in block)
    return (
      <ul className="list-disc space-y-1.5 pl-5 leading-7">
        {block.list.map((item) => (
          <li key={item}><Rich text={item} /></li>
        ))}
      </ul>
    );
  if ("steps" in block)
    return (
      <ol className="list-decimal space-y-1.5 pl-5 leading-7">
        {block.steps.map((item) => (
          <li key={item}><Rich text={item} /></li>
        ))}
      </ol>
    );
  if ("example" in block) {
    const e = block.example;
    return (
      <Card title={`Example: ${e.title}`} className="bg-surface-2/50">
        {e.rows && (
          <dl className="text-sm">
            {e.rows.map(([k, v]) => (
              <div key={k} className="border-t border-line py-1.5 first:border-t-0 sm:flex sm:gap-4">
                <dt className="text-muted sm:w-56 sm:shrink-0">{k}</dt>
                <dd className="font-medium">{v}</dd>
              </div>
            ))}
          </dl>
        )}
        {e.lines && (
          <ul className="space-y-1 text-sm">
            {e.lines.map((l) => (
              <li key={l}><Rich text={l} /></li>
            ))}
          </ul>
        )}
        {e.result && (
          <p className="mt-3 border-t border-line pt-3 text-sm"><Rich text={e.result} /></p>
        )}
      </Card>
    );
  }
  if ("table" in block)
    return (
      <Table>
        <thead>
          <tr>
            {block.table.head.map((h) => (
              <Th key={h}>{h}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.table.rows.map((row) => (
            <tr key={row.join("|")}>
              {row.map((cell, i) => (
                <Td key={i}><Rich text={cell} /></Td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
    );
  if ("analogy" in block)
    return (
      <div className="rounded-xl border border-line bg-surface-2/60 px-4 py-3 text-sm leading-6">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Think of it like this</p>
        <Rich text={block.analogy} />
      </div>
    );
  if ("try" in block) {
    const t = block.try;
    return (
      <Card title="Your turn" subtitle="Work it out first, then check." className="border-accent/40">
        <p className="leading-7"><Rich text={t.q} /></p>
        <details className="group mt-3">
          <summary className="cursor-pointer select-none text-sm font-medium text-accent">
            <span className="group-open:hidden">Show the working</span>
            <span className="hidden group-open:inline">Hide the working</span>
          </summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-6">
            {t.work.map((line) => (
              <li key={line}><Rich text={line} /></li>
            ))}
          </ol>
          <p className="mt-3 border-t border-line pt-3 text-sm font-medium"><Rich text={t.a} /></p>
        </details>
      </Card>
    );
  }
  if ("recap" in block)
    return (
      <Card title="Remember" className="bg-surface-2/50">
        <ul className="space-y-1.5 text-sm leading-6">
          {block.recap.map((item) => (
            <li key={item} className="flex gap-2">
              <span aria-hidden className="text-good">✓</span>
              <span><Rich text={item} /></span>
            </li>
          ))}
        </ul>
      </Card>
    );
  if ("tip" in block)
    return (
      <Notice tone="accent">
        <span className="font-semibold">Tip: </span>
        <Rich text={block.tip} />
      </Notice>
    );
  if ("warn" in block)
    return (
      <Notice tone="warn">
        <span className="font-semibold">Watch out: </span>
        <Rich text={block.warn} />
      </Notice>
    );
  return <Diagram name={block.diagram} />;
}

export default async function LessonPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const lesson = lessonBySlug(slug);
  if (!lesson) notFound();
  const index = LESSONS.indexOf(lesson);
  const prev = LESSONS[index - 1];
  const next = LESSONS[index + 1];
  const track = TRACKS.find((t) => t.key === lesson.track);
  const inTrack = LESSONS.filter((l) => l.track === lesson.track);
  const position = inTrack.indexOf(lesson) + 1;

  return (
    <Page width="narrow">
      <nav className="text-sm text-muted">
        <Link href="/learn" className="hover:underline">
          Learn
        </Link>{" "}
        · {track?.title} · lesson {position} of {inTrack.length}
      </nav>
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{lesson.title}</h1>
        <p className="mt-1 text-sm text-muted">
          {lesson.summary} · {lesson.minutes} min
        </p>
      </header>
      <Notice tone="accent">
        <p className="font-semibold">By the end you can</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5">
          {lesson.goals.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      </Notice>
      <article className="space-y-4">
        {lesson.blocks.map((b, i) => (
          <BlockView key={i} block={b} />
        ))}
      </article>
      {lesson.quiz.length > 0 ? (
        <Card title="Check yourself" subtitle="Answer every question correctly to mark the lesson done.">
          <Quiz slug={lesson.slug} questions={lesson.quiz} />
        </Card>
      ) : (
        <MarkRead slug={lesson.slug} />
      )}
      <nav className="flex flex-wrap justify-between gap-3 border-t border-line pt-4 text-sm">
        {prev ? (
          <Link href={`/learn/${prev.slug}`} className="hover:underline">
            ← {prev.title}
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link href={`/learn/${next.slug}`} className="text-right font-medium text-accent hover:underline">
            Next: {next.title} →
          </Link>
        ) : (
          <Link href="/learn" className="font-medium text-accent hover:underline">
            Back to all lessons
          </Link>
        )}
      </nav>
    </Page>
  );
}
