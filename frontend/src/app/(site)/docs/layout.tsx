import type { ReactNode } from "react";

import { DocsNav } from "@/components/docs/docs-nav";
import { Container } from "@/components/site/blocks";
import { docsNav } from "@/lib/docs";

// The documentation: a menu on the left (every page listed the same way) and the page on the right.
export default function DocsLayout({ children }: { children: ReactNode }) {
  const nav = docsNav().map((g) => ({ group: g.group, items: g.items.map(({ slug, title }) => ({ slug, title })) }));
  return (
    <Container className="py-10 lg:flex lg:gap-12 lg:py-14">
      <DocsNav nav={nav} />
      <div className="min-w-0 flex-1">{children}</div>
    </Container>
  );
}
