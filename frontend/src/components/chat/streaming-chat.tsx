"use client";

import { ShieldCheck } from "lucide-react";
import { useRef, useState } from "react";

import { Alert, Button, Card, PageHeader } from "@/components/ui";
import { streamAnswer, type StreamItem } from "@/lib/answer-stream";

interface FinalCitation {
  number: number;
  chunk_id: string;
  document_title: string;
  section: string | null;
  pages: string;
}

interface StreamTurn {
  key: string;
  question: string;
  items: StreamItem[];
  done: boolean;
  outcome?: string;
  citations: FinalCitation[];
  error?: string;
}

// Sentence-gated answers (blueprint 11.6, 17.3): each sentence appears only after the validator passed it and its
// audit record committed; a removed sentence shows a marker instead of its text.
export function StreamingChat() {
  const [turns, setTurns] = useState<StreamTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);

  function update(key: string, fn: (t: StreamTurn) => StreamTurn) {
    setTurns((all) => all.map((t) => (t.key === key ? fn(t) : t)));
  }

  async function ask() {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    const key = crypto.randomUUID();
    setTurns((t) => [...t, { key, question: q, items: [], done: false, citations: [] }]);
    setQuestion("");
    setBusy(true);
    abort.current = new AbortController();
    await streamAnswer(q, {
      onItem: (item) => { update(key, (t) => ({ ...t, items: [...t.items.filter((i) => i.seq !== item.seq), item] })); },
      onDone: (d) => { update(key, (t) => ({ ...t, done: true, outcome: d.outcome, citations: d.citations as FinalCitation[] })); },
      onError: (detail) => { update(key, (t) => ({ ...t, done: true, error: detail })); },
    }, abort.current.signal);
    setBusy(false);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Ask" subtitle="Answers arrive sentence by sentence, each one checked against your documents before you see it." />
      <div className="space-y-4" aria-live="polite">
        {turns.map((t) => (
          <Card key={t.key} className="p-4">
            <p className="font-medium text-ink-900">{t.question}</p>
            <div className="mt-3 space-y-1 text-ink-800">
              {t.items.sort((a, b) => a.seq - b.seq).map((i) => i.kind === "stripped" ? (
                <p key={i.seq} className="text-xs text-ink-400 italic">A sentence was removed because the documents do not support it.</p>
              ) : (
                <p key={i.seq}>{i.text}{" "}
                  {i.citations.map((c) => <sup key={c.chunk_id} className="text-brand-600">[{c.number}]</sup>)}</p>
              ))}
              {!t.done && <p className="text-xs text-ink-400">Checking the next sentence…</p>}
            </div>
            {t.error && <div className="mt-2"><Alert tone="amber">{t.error}</Alert></div>}
            {t.done && t.citations.length > 0 && (
              <ol className="mt-3 space-y-0.5 border-t border-ink-100 pt-2 text-xs text-ink-600">
                {t.citations.map((c) => (
                  <li key={c.chunk_id}>[{c.number}] {c.document_title}{c.section ? ` · ${c.section}` : ""}{c.pages ? ` · p. ${c.pages}` : ""}</li>
                ))}
              </ol>
            )}
            {t.done && !t.error && (
              <p className="mt-2 flex items-center gap-1 text-xs text-ink-500"><ShieldCheck className="size-3.5" aria-hidden />
                {t.outcome === "answered" ? "Every sentence shown passed citation validation." : "The documents do not answer this."}</p>
            )}
          </Card>
        ))}
      </div>
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(); }}>
        <label htmlFor="stream-question" className="sr-only">Question</label>
        <input id="stream-question" className="flex-1 rounded-lg border border-ink-200 p-2.5" value={question}
          maxLength={2000} onChange={(e) => { setQuestion(e.target.value); }} placeholder="Ask about your documents" />
        <Button type="submit" busy={busy} disabled={question.trim().length < 3}>Ask</Button>
        {busy && <Button variant="ghost" onClick={() => abort.current?.abort()}>Stop</Button>}
      </form>
    </div>
  );
}
