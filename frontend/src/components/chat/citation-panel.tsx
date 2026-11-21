"use client";

import { FileText, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { pages } from "@/lib/format";
import type { Citation } from "@/lib/types";

/** Split source text into plain and highlighted parts. Rendered as text nodes only: no HTML injection. */
function parts(text: string, highlights: [number, number][]): { text: string; mark: boolean }[] {
  const spans = [...highlights].sort((a, b) => a[0] - b[0]);
  const out: { text: string; mark: boolean }[] = [];
  let pos = 0;
  for (const [start, end] of spans) {
    if (end <= pos) continue;
    const s = Math.max(start, pos);
    if (s > pos) out.push({ text: text.slice(pos, s), mark: false });
    out.push({ text: text.slice(s, end), mark: true });
    pos = end;
  }
  if (pos < text.length) out.push({ text: text.slice(pos), mark: false });
  return out;
}

export function CitationPanel({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const first = useRef<HTMLElement>(null);
  useEffect(() => {
    first.current?.scrollIntoView({ block: "center" });
  }, [citation]);

  return (
    <aside className="flex w-[26rem] shrink-0 flex-col border-l border-ink-200 bg-surface" aria-label="Source">
      <div className="flex items-start gap-3 border-b border-ink-100 px-5 py-4">
        <div className="rounded-lg bg-brand-50 p-2 text-link">
          <FileText className="size-4" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-brand-700">Source {citation.n}</p>
          <h2 className="text-sm font-semibold text-ink-950">{citation.document_title}</h2>
          <p className="mt-0.5 text-xs text-ink-500">
            {[citation.section, pages(citation.page_start, citation.page_end)].filter(Boolean).join(" · ")}
          </p>
        </div>
        <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-400 hover:bg-ink-100" aria-label="Close source">
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {citation.text ? (
          <p className="text-sm leading-6 whitespace-pre-wrap text-ink-700">
            {(() => {
              const segments = parts(citation.text, citation.highlights);
              const firstMark = segments.findIndex((p) => p.mark);
              return segments.map((p, i) =>
                p.mark ? (
                  <mark key={i} className="cite" ref={i === firstMark ? first : undefined}>
                    {p.text}
                  </mark>
                ) : (
                  <span key={i}>{p.text}</span>
                ),
              );
            })()}
          </p>
        ) : (
          <p className="rounded-lg bg-ink-50 p-3 text-sm text-ink-600">
            This source is no longer available to you. It was deleted or your access changed after the answer was given.
          </p>
        )}
      </div>
      <p className="border-t border-ink-100 px-5 py-3 text-xs text-ink-500">
        Highlighted text is the exact passage the sentence was verified against.
      </p>
    </aside>
  );
}
