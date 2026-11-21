import { ArrowLeft, ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Article } from "@/components/docs/article";
import { Wall, type WallReason } from "@/components/docs/wall";
import { findMe } from "@/lib/backend";
import { TIER_LABEL, canRead, getDoc, neighbours } from "@/lib/docs";

type Params = { params: Promise<{ slug: string }> };

const ROLE_NAME = { tenant: "a Member", admin: "an Admin", super_admin: "a Super Admin" } as const;

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const doc = getDoc((await params).slug);
  return doc ? { title: `${doc.title} · Docs`, description: doc.summary } : {};
}

export default async function DocPage({ params }: Params) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) notFound();

  // Access is decided here, on the server, from the role the gateway reports (never from the browser). A page the
  // reader may not open is replaced by the wall before anything is sent, so its text never reaches the browser.
  let reason: WallReason | null = null;
  let role = "";
  if (doc.tier !== "public") {
    const me = await findMe();
    if (me === "unavailable") reason = "unavailable";
    else if (!me) reason = "signed-out";
    else if (!me.membership?.active) reason = "inactive";
    else if (!canRead(doc.tier, me.membership.role)) {
      reason = "role";
      role = ROLE_NAME[me.membership.role];
    }
  }
  const open = reason === null;
  const headings = open ? doc.blocks.filter((b) => b.t === "h2") : [];
  const { prev, next } = neighbours(doc.slug);

  return (
    <div className="xl:flex xl:gap-12">
      <article className="min-w-0 flex-1">
        <p className="font-mono text-xs tracking-wider text-ink-500 uppercase">{doc.group}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink-950 md:text-4xl">{doc.title}</h1>
        <p className="mt-3 max-w-2xl text-lg leading-8 text-ink-600">{doc.summary}</p>
        <div className="mt-10 max-w-3xl">
          {open ? (
            <Article blocks={doc.blocks} />
          ) : (
            <Wall reason={reason!} audience={doc.tier === "public" ? "" : TIER_LABEL[doc.tier]} role={role} />
          )}
        </div>

        <nav className="mt-16 grid max-w-3xl gap-4 border-t border-ink-200 pt-8 sm:grid-cols-2" aria-label="More pages">
          {prev ? (
            <Link href={`/docs/${prev.slug}`} className="group rounded-xl border border-ink-200 bg-surface px-5 py-4 hover:border-ink-400">
              <span className="flex items-center gap-1.5 text-xs text-ink-500">
                <ArrowLeft className="size-3.5 transition-transform group-hover:-translate-x-0.5" aria-hidden /> Previous
              </span>
              <span className="mt-1 block font-medium text-ink-950">{prev.title}</span>
            </Link>
          ) : (
            <span />
          )}
          {next && (
            <Link
              href={`/docs/${next.slug}`}
              className="group rounded-xl border border-ink-200 bg-surface px-5 py-4 text-right hover:border-ink-400"
            >
              <span className="flex items-center justify-end gap-1.5 text-xs text-ink-500">
                Next <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </span>
              <span className="mt-1 block font-medium text-ink-950">{next.title}</span>
            </Link>
          )}
        </nav>
      </article>

      {headings.length > 0 && (
        <aside className="hidden w-52 shrink-0 xl:block" aria-label="On this page">
          <div className="sticky top-24">
            <p className="font-mono text-[11px] tracking-wider text-ink-400 uppercase">On this page</p>
            <ul className="mt-3 space-y-2 border-l border-ink-200">
              {headings.map((h) =>
                h.t === "h2" ? (
                  <li key={h.id}>
                    <a href={`#${h.id}`} className="-ml-px block border-l border-transparent pl-3 text-sm text-ink-600 hover:border-ink-500 hover:text-ink-950">
                      {h.text}
                    </a>
                  </li>
                ) : null,
              )}
            </ul>
          </div>
        </aside>
      )}
    </div>
  );
}
