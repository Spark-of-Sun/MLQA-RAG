"use client";

import { ArrowUp, MessageSquareText, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AnswerView } from "@/components/chat/answer-view";
import { CitationPanel } from "@/components/chat/citation-panel";
import { Alert } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { timeAgo } from "@/lib/format";
import type { Answer, Citation, HistoryItem } from "@/lib/types";

type Turn = { key: string; question: string; answer?: Answer; error?: string };

const EXAMPLES: Record<string, string[]> = {
  legal: [
    "When must the severance benefit be paid, and what conditions apply?",
    "What notice is required to terminate the agreement?",
    "Which law governs this agreement?",
  ],
  medical: [
    "What is the recommended starting dosage for hypertension?",
    "What are the contraindications?",
    "What adverse reactions were reported most often?",
  ],
};

export function Chat({ kind }: { kind: "legal" | "medical" | "both" }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [selected, setSelected] = useState<Citation | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const examples = kind === "both" ? [...EXAMPLES.legal!.slice(0, 2), EXAMPLES.medical![0]!] : EXAMPLES[kind]!;

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.get<HistoryItem[]>("queries?limit=30"));
    } catch {
      /* history is optional */
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    api
      .get<{ status: string }[]>("documents")
      .then((docs) => setDocCount(docs.filter((d) => d.status === "ready").length))
      .catch(() => setDocCount(null));
  }, [loadHistory]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  async function ask(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    const key = crypto.randomUUID();
    setTurns((t) => [...t, { key, question: q }]);
    setQuestion("");
    setBusy(true);
    setSelected(null);
    try {
      const answer = await api.post<Answer>("queries", { question: q });
      setTurns((t) => t.map((turn) => (turn.key === key ? { ...turn, answer } : turn)));
      void loadHistory();
    } catch (e) {
      setTurns((t) => t.map((turn) => (turn.key === key ? { ...turn, error: errorMessage(e) } : turn)));
    } finally {
      setBusy(false);
    }
  }

  async function openPast(id: string) {
    setSelected(null);
    try {
      const answer = await api.get<Answer>(`queries/${id}`);
      setTurns([{ key: id, question: answer.question, answer }]);
    } catch (e) {
      setTurns([{ key: id, question: "", error: errorMessage(e) }]);
    }
  }

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-ink-200 bg-white/60 lg:flex">
        <div className="p-3">
          <button
            type="button"
            onClick={() => {
              setTurns([]);
              setSelected(null);
            }}
            className="flex w-full items-center gap-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50"
          >
            <Plus className="size-4" aria-hidden /> New question
          </button>
        </div>
        <p className="px-4 pb-1 text-xs font-medium tracking-wide text-ink-400 uppercase">Recent</p>
        <ul className="flex-1 overflow-y-auto px-2 pb-3">
          {history.map((h) => (
            <li key={h.id}>
              <button
                type="button"
                onClick={() => openPast(h.id)}
                className="w-full rounded-lg px-2.5 py-2 text-left hover:bg-ink-100"
              >
                <p className="line-clamp-2 text-sm text-ink-800">{h.question}</p>
                <p className="mt-0.5 text-xs text-ink-400">
                  {h.outcome === "refused" ? "Not in documents" : h.outcome === "partial" ? "Partly answered" : "Answered"} ·{" "}
                  {timeAgo(h.created_at)}
                </p>
              </button>
            </li>
          ))}
          {history.length === 0 && <li className="px-2.5 py-2 text-sm text-ink-400">No questions yet.</li>}
        </ul>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {turns.length === 0 && (
              <div className="pt-10 text-center">
                <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
                  <MessageSquareText className="size-6" aria-hidden />
                </div>
                <h1 className="text-2xl font-semibold tracking-tight text-ink-950">Ask your documents</h1>
                <p className="mx-auto mt-2 max-w-lg text-sm text-ink-500">
                  Answers use only the documents you can access. Every sentence is checked against the passage it
                  cites; anything that cannot be verified is removed.
                </p>
                {docCount === 0 && (
                  <div className="mx-auto mt-6 max-w-md">
                    <Alert tone="amber">
                      No documents are ready yet.{" "}
                      <Link href="/library" className="font-medium underline">
                        Upload one in the Library
                      </Link>
                      .
                    </Alert>
                  </div>
                )}
                <div className="mx-auto mt-8 grid max-w-xl gap-2">
                  {examples.map((ex) => (
                    <button
                      key={ex}
                      type="button"
                      onClick={() => ask(ex)}
                      className="rounded-xl border border-ink-200 bg-white px-4 py-3 text-left text-sm text-ink-700 shadow-sm hover:border-brand-200 hover:bg-brand-50/40"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-8">
              {turns.map((turn) => (
                <div key={turn.key}>
                  {turn.question && (
                    <div className="mb-3 flex justify-end">
                      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-ink-900 px-4 py-2.5 text-sm text-white">
                        {turn.question}
                      </p>
                    </div>
                  )}
                  {turn.answer && (
                    <AnswerView answer={turn.answer} selected={selected} onSelect={(c) => setSelected(c)} />
                  )}
                  {turn.error && <Alert>{turn.error}</Alert>}
                  {!turn.answer && !turn.error && <Working elapsed={elapsed} />}
                </div>
              ))}
            </div>
            <div ref={bottom} />
          </div>
        </div>

        <form
          className="border-t border-ink-200 bg-white px-6 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(question);
          }}
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-ink-200 bg-white p-2 shadow-sm focus-within:border-brand-300">
            <label htmlFor="question" className="sr-only">
              Your question
            </label>
            <textarea
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask(question);
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder="Ask a question about your documents…"
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-ink-400"
            />
            <button
              type="submit"
              disabled={busy || question.trim().length < 3}
              className="flex size-9 items-center justify-center rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:bg-ink-200"
              aria-label="Ask"
            >
              <ArrowUp className="size-4" aria-hidden />
            </button>
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-ink-400">
            Reports what your documents say. Not legal or medical advice.
          </p>
        </form>
      </div>

      {selected && <CitationPanel citation={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function Working({ elapsed }: { elapsed: number }) {
  return (
    <div className="rounded-2xl border border-ink-200 bg-white p-4" aria-live="polite">
      <div className="flex items-center gap-2 text-sm font-medium text-ink-700">
        <span className="flex gap-1" aria-hidden>
          <span className="dot size-1.5 rounded-full bg-brand-500" />
          <span className="dot size-1.5 rounded-full bg-brand-500 [animation-delay:0.2s]" />
          <span className="dot size-1.5 rounded-full bg-brand-500 [animation-delay:0.4s]" />
        </span>
        Searching, drafting and verifying every sentence…
        <span className="ml-auto text-xs font-normal text-ink-400">{elapsed}s</span>
      </div>
      <p className="mt-1.5 text-xs text-ink-500">
        Nothing is shown until each sentence has passed its citation checks. This usually takes 5 to 20 seconds.
      </p>
    </div>
  );
}
