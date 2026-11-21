import { Info, TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { Block } from "@/lib/docs";

// Renders documentation blocks as plain React elements (text nodes only, no HTML injection). Inline markup:
// **bold**, `code` and [label](/path).

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink-950">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="rounded bg-ink-100 px-1 py-0.5 font-mono text-[0.85em] text-ink-900">
          {part.slice(1, -1)}
        </code>
      );
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      return (
        <Link key={i} href={link[2]!} className="font-medium text-link underline decoration-1 underline-offset-4 hover:decoration-2">
          {link[1]}
        </Link>
      );
    }
    return part;
  });
}

export function Article({ blocks }: { blocks: Block[] }) {
  return (
    <div className="space-y-5 text-[15px] leading-7 text-ink-700">
      {blocks.map((b, i) => {
        switch (b.t) {
          case "p":
            return <p key={i}>{inline(b.text)}</p>;
          case "h2":
            return (
              <h2 key={i} id={b.id} className="scroll-mt-24 pt-6 text-xl font-semibold tracking-tight text-ink-950">
                <a href={`#${b.id}`} className="group">
                  {b.text}
                  <span className="ml-2 text-ink-300 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden>
                    #
                  </span>
                </a>
              </h2>
            );
          case "list":
            return (
              <ul key={i} className="space-y-2 pl-1">
                {b.items.map((it, j) => (
                  <li key={j} className="flex gap-3">
                    <span className="mt-[11px] size-1.5 shrink-0 rounded-full bg-ink-400" aria-hidden />
                    <span>{inline(it)}</span>
                  </li>
                ))}
              </ul>
            );
          case "steps":
            return (
              <ol key={i} className="space-y-3">
                {b.items.map((it, j) => (
                  <li key={j} className="flex gap-4">
                    <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-ink-200 bg-surface font-mono text-xs text-ink-600">
                      {j + 1}
                    </span>
                    <span>{inline(it)}</span>
                  </li>
                ))}
              </ol>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-xl border border-ink-200 bg-surface">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-ink-200 bg-ink-50 text-xs text-ink-600">
                    <tr>
                      {b.head.map((h, j) => (
                        <th key={j} className="px-4 py-2.5 font-medium">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {b.rows.map((row, j) => (
                      <tr key={j} className="align-top">
                        {row.map((cell, k) => (
                          <td key={k} className={`px-4 py-2.5 leading-6 ${k === 0 ? "font-medium text-ink-900" : "text-ink-700"}`}>
                            {inline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "note": {
            const warn = b.tone === "warn";
            const Icon = warn ? TriangleAlert : Info;
            return (
              <div
                key={i}
                className={`flex gap-3 rounded-xl border px-4 py-3 text-sm leading-6 ${
                  warn ? "border-amber-200 bg-amber-50 text-amber-900" : "border-brand-200 bg-brand-50 text-brand-900"
                }`}
              >
                <Icon className="mt-1 size-4 shrink-0" aria-hidden />
                <p>{inline(b.text)}</p>
              </div>
            );
          }
          case "code":
            return (
              <pre key={i} className="overflow-x-auto rounded-xl border border-ink-200 bg-ink-50 px-4 py-3 font-mono text-[13px] leading-6 text-ink-800">
                {b.text}
              </pre>
            );
        }
      })}
    </div>
  );
}
