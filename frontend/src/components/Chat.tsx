"use client";

import { useRef, useState } from "react";
import { ask } from "@/lib/api-client";
import { readStream, type Citation, type StreamEvent } from "@/lib/sse";
import { Notice } from "@/components/Shell";

interface Line {
  kind: "sentence" | "notice";
  text: string;
  aliases?: string[];
  tone?: "stripped" | "refusal";
}

const STAGE_LABEL: Record<string, string> = { retrieving: "Finding passages…", generating: "Drafting…", validating: "Verifying every claim…" };
const ERRORS: Record<string, string> = {
  forbidden: "You do not have access to anything that can answer this.",
  retrieval_unavailable: "The search service is unavailable. Please try again shortly.",
  generation_unavailable: "The answer service is unavailable. Please try again shortly.",
  validator_unavailable: "Verification is unavailable, so no answer was released.",
  audit_unavailable: "The audit trail is unavailable, so no answer was released.",
  revoked: "Your access changed during this answer, so it was stopped.",
};

export function Chat() {
  const [question, setQuestion] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<Citation | null>(null);
  const abort = useRef<AbortController | null>(null);
  const lastEvent = useRef<string | undefined>(undefined);

  function apply(event: StreamEvent) {
    if (event.id) lastEvent.current = event.id;
    if (event.type === "status") setStatus(STAGE_LABEL[event.stage] ?? null);
    else if (event.type === "sentence") {
      setLines((prev) => [...prev, { kind: "sentence", text: event.text, aliases: event.aliases }]);
      setCitations((prev) => [...prev, ...event.citations]);
      setStatus(null);
    } else if (event.type === "notice") setLines((prev) => [...prev, { kind: "notice", text: event.text, tone: event.kind }]);
    else if (event.type === "citations") setCitations(event.citations);
    else if (event.type === "error") setError(ERRORS[event.code] ?? "The answer could not be completed.");
    else if (event.type === "done") setStatus(null);
  }

  async function submit(resume = false) {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    if (!resume) {
      setLines([]);
      setCitations([]);
      setActive(null);
      lastEvent.current = undefined;
    }
    setError(null);
    setStatus("Finding passages…");
    try {
      const response = await ask(question, controller.signal, resume ? lastEvent.current : undefined);
      if (!response.ok) throw new Error(String(response.status));
      for await (const event of readStream(response)) apply(event);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      // A dropped connection resumes with Last-Event-ID: only already released, audited sentences are replayed.
      if (lastEvent.current && !resume) return void submit(true);
      setError("The connection was interrupted. Please try again.");
    } finally {
      setStatus((s) => (controller.signal.aborted ? s : null));
    }
  }

  const used = lines.flatMap((l) => l.aliases ?? []);
  const panel = citations.filter((c, i, all) => used.includes(c.alias) && all.findIndex((x) => x.alias === c.alias && x.doc_title === c.doc_title) === i);

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <section aria-label="Question and answer" className="space-y-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
          className="flex gap-2"
        >
          <label htmlFor="question" className="sr-only">Your question</label>
          <input id="question" required maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about your documents…" className="flex-1 rounded border border-slate-300 px-3 py-2" />
          <button className="rounded bg-indigo-700 px-4 py-2 text-white">Ask</button>
        </form>
        {status && <Notice>{status}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        <div aria-live="polite" className="space-y-2">
          {lines.map((line, i) =>
            line.kind === "notice" ? (
              <Notice key={i} tone={line.tone === "refusal" ? "info" : "warn"}>{line.text}</Notice>
            ) : (
              <p key={i} className="leading-relaxed">
                {line.text.split(/(\[chunk_\d+\])/g).map((part, j) => {
                  const m = /^\[(chunk_\d+)\]$/.exec(part);
                  const cite = m ? citations.find((c) => c.alias === m[1]) : undefined;
                  return m ? (
                    <button key={j} type="button" onClick={() => cite && setActive(cite)} className="mx-0.5 rounded bg-indigo-100 px-1 text-xs text-indigo-900 hover:bg-indigo-200" aria-label={`Show source ${m[1]}`}>
                      {m[1]?.replace("chunk_", "")}
                    </button>
                  ) : (
                    <span key={j}>{part}</span>
                  );
                })}
              </p>
            ),
          )}
        </div>
      </section>
      <aside aria-label="Sources" className="space-y-3 rounded-lg bg-white p-4 shadow-sm">
        <h2 className="font-medium">Sources</h2>
        {panel.length === 0 && <p className="text-sm text-slate-500">Cited sources appear here. Click a number to see where it came from.</p>}
        <ul className="space-y-2">
          {panel.map((c) => (
            <li key={`${c.alias}-${c.doc_title}`}>
              <button type="button" onClick={() => setActive(c)} className={`w-full rounded border p-2 text-left text-sm ${active?.alias === c.alias ? "border-indigo-600" : "border-slate-200"}`}>
                <span className="font-medium">{c.doc_title}</span>
                <span className="block text-slate-600">
                  {c.page_start === c.page_end ? `Page ${c.page_start}` : `Pages ${c.page_start}–${c.page_end}`}
                  {c.clause_no ? `, clause ${c.clause_no}` : ""}
                </span>
                <span className="block text-xs text-slate-500">{c.section_path}</span>
              </button>
            </li>
          ))}
        </ul>
        {active && <p className="rounded bg-yellow-50 p-2 text-xs text-yellow-900">Highlighted span {active.span_start}–{active.span_end} of the cited passage (version {active.doc_version}).</p>}
      </aside>
    </div>
  );
}
