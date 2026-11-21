"use client";

import { Ban, ChevronDown, CircleCheck, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { pages } from "@/lib/format";
import type { Answer, Check, Citation } from "@/lib/types";

export function AnswerView({
  answer,
  selected,
  onSelect,
}: {
  answer: Answer;
  selected: Citation | null;
  onSelect: (c: Citation) => void;
}) {
  const [details, setDetails] = useState(false);
  const byN = new Map(answer.citations.map((c) => [c.n, c]));
  const sentences = answer.segments.filter((s) => s.type === "sentence");
  const removed = answer.segments.filter((s) => s.type === "removed");
  const refusal = answer.segments.find((s) => s.type === "refusal");
  const s = answer.stats;

  return (
    <div className="rounded-2xl border border-ink-200 bg-surface p-5 shadow-sm">
      {sentences.length > 0 && (
        <p className="text-[15px] leading-7 text-ink-900">
          {sentences.map((seg, i) => (
            <span key={i}>
              {seg.text}
              {seg.citations.map((n) => {
                const c = byN.get(n);
                const active = selected?.chunk_id === c?.chunk_id && selected?.n === n;
                return (
                  <button
                    key={n}
                    type="button"
                    onClick={() => c && onSelect(c)}
                    className={`ml-0.5 -translate-y-1 rounded px-1 align-baseline text-[11px] font-semibold ${
                      active ? "bg-brand-600 text-white" : "bg-brand-100 text-brand-700 hover:bg-brand-200"
                    }`}
                    aria-label={`Show source ${n}`}
                  >
                    {n}
                  </button>
                );
              })}{" "}
            </span>
          ))}
        </p>
      )}

      {refusal && (
        <div
          className={`flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-sm text-amber-900 ${
            sentences.length ? "mt-3" : ""
          }`}
        >
          <Ban className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div>
            <p className="font-medium">{refusal.text}</p>
            {sentences.length === 0 && (
              <p className="mt-0.5 text-xs text-amber-800">
                Nothing in the documents you can access supports an answer, so none was given.
              </p>
            )}
          </div>
        </div>
      )}

      {removed.map((seg, i) => (
        <div key={i} className="mt-3 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2 text-sm text-rose-800">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            A claim in this answer could not be verified and was removed.{" "}
            <span className="text-rose-700/80">({seg.reason})</span>
          </p>
        </div>
      ))}

      {answer.citations.length > 0 && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {answer.citations.map((c) => (
            <button
              key={c.n}
              type="button"
              onClick={() => onSelect(c)}
              className={`flex items-start gap-2.5 rounded-xl border px-3 py-2 text-left hover:border-brand-200 hover:bg-brand-50/40 ${
                selected?.chunk_id === c.chunk_id ? "border-brand-300 bg-brand-50/60" : "border-ink-200"
              }`}
            >
              <span className="mt-0.5 rounded bg-brand-100 px-1.5 text-[11px] font-semibold text-brand-700">{c.n}</span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-ink-800">{c.document_title}</span>
                <span className="block truncate text-xs text-ink-500">
                  {[c.section, pages(c.page_start, c.page_end)].filter(Boolean).join(" · ") || "Excerpt"}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 border-t border-ink-100 pt-3">
        <button
          type="button"
          onClick={() => setDetails((d) => !d)}
          className="flex w-full items-center gap-2 text-left text-xs text-ink-500 hover:text-ink-700"
          aria-expanded={details}
        >
          {s.verified > 0 ? (
            <ShieldCheck className="size-3.5 text-emerald-600" aria-hidden />
          ) : (
            <ShieldAlert className="size-3.5 text-amber-600" aria-hidden />
          )}
          <span>
            {s.verified} sentence{s.verified === 1 ? "" : "s"} verified
            {s.removed ? ` · ${s.removed} removed` : ""}
            {s.sources_considered != null ? ` · ${s.sources_considered} passages considered` : ""}
            {s.latency_ms != null ? ` · ${(s.latency_ms / 1000).toFixed(1)} s` : ""}
          </span>
          <ChevronDown className={`ml-auto size-3.5 transition-transform ${details ? "rotate-180" : ""}`} aria-hidden />
        </button>
        {details && (
          <div className="mt-3 space-y-3">
            {answer.segments.map((seg, i) =>
              seg.type === "refusal" ? null : (
                <div key={i} className="rounded-lg bg-ink-50 p-3">
                  <p className="text-xs font-medium text-ink-700">
                    {seg.type === "sentence" ? `“${seg.text}”` : "Removed claim"}
                  </p>
                  <Checks checks={seg.checks} />
                </div>
              ),
            )}
            {s.model && <p className="text-xs text-ink-400">Model {s.model}. Checks run on the original source text.</p>}
          </div>
        )}
      </div>
    </div>
  );
}

function Checks({ checks }: { checks: Check[] }) {
  return (
    <ul className="mt-2 grid gap-1 sm:grid-cols-2">
      {checks.map((c) => (
        <li key={c.code} className="flex items-start gap-1.5 text-xs" title={c.detail || undefined}>
          {c.ok ? (
            <CircleCheck className="mt-px size-3.5 shrink-0 text-emerald-600" aria-hidden />
          ) : (
            <ShieldAlert className="mt-px size-3.5 shrink-0 text-rose-600" aria-hidden />
          )}
          <span className={c.ok ? "text-ink-600" : "text-rose-700"}>
            {c.label}
            {!c.ok && c.detail ? `: ${c.detail}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
