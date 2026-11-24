import type { ReactNode } from "react";

import { Label, Prose } from "@/components/site/blocks";

/**
 * One legal document. Every legal text on the site is a placeholder written from what the product does today
 * (src/lib/docs.ts); it must be reviewed by counsel before it is relied on, and says so at the top.
 */
export function LegalDoc({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <>
      <Label>Legal</Label>
      <h1 className="mt-5 text-4xl leading-tight font-medium text-ink-950 md:text-5xl">{title}</h1>
      <p className="mt-5 max-w-3xl text-lg leading-8 text-ink-600">{intro}</p>
      <div role="note" className="mt-8 max-w-3xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-900">
        <strong>Draft for review by counsel.</strong> This text is a placeholder that describes how the service works
        today. It has not been reviewed by a lawyer and is not yet a binding agreement or notice.
      </div>
      <div className="mt-4">
        <Prose>{children}</Prose>
      </div>
    </>
  );
}
