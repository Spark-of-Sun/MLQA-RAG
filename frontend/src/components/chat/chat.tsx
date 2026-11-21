"use client";

import { ArrowUp, CornerDownRight, History, MessageSquareText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AnswerView } from "@/components/chat/answer-view";
import { CitationPanel } from "@/components/chat/citation-panel";
import { Alert, Spinner } from "@/components/ui";
import { ApiError, api, errorMessage, notifyChatsChanged } from "@/lib/api-client";
import { timeAgo } from "@/lib/format";
import type { Answer, ChatDetail, ChatSummary, Citation } from "@/lib/types";

type Turn = { key: string; question: string; answer?: Answer; error?: string };

// Threads already on screen, so switching chats (or the move from /chat to /chat/<id>) shows them at once.
const threadCache = new Map<string, { title: string; turns: Turn[] }>();

const EXAMPLES: Record<string, string[]> = {
  legal: [
    "When must the severance benefit be paid, and what conditions apply?",
    "What notice is required to terminate the agreement?",
    "What is the punishment for murder under Section 302?",
  ],
  medical: [
    "What is the recommended starting dosage for hypertension?",
    "What are the contraindications?",
    "What adverse reactions were reported most often?",
  ],
};

function toTurns(answers: Answer[]): Turn[] {
  return answers.map((a) => ({ key: a.id, question: a.question, answer: a }));
}

export function Chat({ conversationId, kind }: { conversationId: string | null; kind: "legal" | "medical" | "both" }) {
  const router = useRouter();
  const cached = conversationId ? threadCache.get(conversationId) : undefined;
  const [turns, setTurns] = useState<Turn[]>(cached?.turns ?? []);
  const [title, setTitle] = useState<string>(cached?.title ?? "");
  const [loading, setLoading] = useState(Boolean(conversationId) && !cached);
  const [missing, setMissing] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [selected, setSelected] = useState<Citation | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);
  const [lastChat, setLastChat] = useState<ChatSummary | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const turnsRef = useRef<Turn[]>(turns);
  turnsRef.current = turns;
  const examples = kind === "both" ? [EXAMPLES.legal![0]!, EXAMPLES.legal![2]!, EXAMPLES.medical![0]!] : EXAMPLES[kind]!;

  const loadThread = useCallback(async (id: string) => {
    try {
      const chat = await api.get<ChatDetail>(`conversations/${id}`);
      const next = toTurns(chat.turns);
      threadCache.set(id, { title: chat.title, turns: next });
      setTurns(next);
      setTitle(chat.title);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMissing(true);
      else setTurns((t) => (t.length ? t : [{ key: "load-error", question: "", error: errorMessage(e) }]));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (conversationId) {
      void loadThread(conversationId);
    } else {
      api
        .get<ChatSummary[]>("conversations?limit=1")
        .then((list) => setLastChat(list[0] ?? null))
        .catch(() => setLastChat(null));
      api
        .get<{ status: string }[]>("documents")
        .then((docs) => setDocCount(docs.filter((d) => d.status === "ready").length))
        .catch(() => setDocCount(null));
    }
    input.current?.focus();
  }, [conversationId, loadThread]);

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
      const answer = await api.post<Answer>("queries", { question: q, conversation_id: conversationId ?? undefined });
      const id = answer.conversation_id;
      const next = turnsRef.current.map((turn) => (turn.key === key ? { ...turn, answer } : turn));
      setTurns(next);
      threadCache.set(id, { title: answer.conversation_title ?? title, turns: next });
      notifyChatsChanged();
      if (!conversationId) {
        router.replace(`/chat/${id}`); // a new chat now has an address you can come back to
      } else if (answer.conversation_title) {
        setTitle(answer.conversation_title);
      }
    } catch (e) {
      setTurns((t) => t.map((turn) => (turn.key === key ? { ...turn, error: errorMessage(e) } : turn)));
    } finally {
      setBusy(false);
    }
  }

  if (missing) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <p className="font-medium text-ink-900">This chat does not exist or is not yours.</p>
        <Link href="/chat" className="text-sm font-medium text-link hover:underline">
          Start a new chat
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {conversationId && (
          <header className="flex h-12 shrink-0 items-center border-b border-ink-100 bg-surface/80 px-6">
            <h1 className="truncate text-sm font-semibold text-ink-900">{title || "Chat"}</h1>
          </header>
        )}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {loading && <Spinner label="Loading chat…" />}

            {!conversationId && turns.length === 0 && (
              <div className="pt-8 text-center">
                <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-brand-50 text-link">
                  <MessageSquareText className="size-6" aria-hidden />
                </div>
                <h1 className="text-2xl font-semibold tracking-tight text-ink-950">Ask your documents</h1>
                <p className="mx-auto mt-2 max-w-lg text-sm text-ink-500">
                  Answers use only the documents you can access. Ask follow-up questions in the same chat; every
                  sentence is checked against the passage it cites, and anything unverified is removed.
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
                {lastChat && (
                  <Link
                    href={`/chat/${lastChat.id}`}
                    className="mx-auto mt-6 flex max-w-xl items-center gap-3 rounded-xl border border-brand-200 bg-brand-50/60 px-4 py-3 text-left hover:bg-brand-50"
                  >
                    <History className="size-4 shrink-0 text-link" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-medium text-brand-700">Continue where you left off</span>
                      <span className="block truncate text-sm text-ink-800">{lastChat.title}</span>
                    </span>
                    <span className="shrink-0 text-xs text-ink-500">{timeAgo(lastChat.updated_at)}</span>
                  </Link>
                )}
                <div className="mx-auto mt-6 grid max-w-xl gap-2">
                  {examples.map((ex) => (
                    <button
                      key={ex}
                      type="button"
                      onClick={() => ask(ex)}
                      className="rounded-xl border border-ink-200 bg-surface px-4 py-3 text-left text-sm text-ink-700 shadow-sm hover:border-brand-200 hover:bg-brand-50/40"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-8">
              {turns.map((turn, i) => {
                const rewritten =
                  turn.answer?.standalone_question &&
                  turn.answer.standalone_question.trim().toLowerCase() !== turn.question.trim().toLowerCase();
                return (
                  <div key={turn.key}>
                    {turn.question && (
                      <div className="mb-3 flex flex-col items-end">
                        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-inverse px-4 py-2.5 text-sm text-on-inverse">
                          {turn.question}
                        </p>
                        {rewritten && i > 0 && (
                          <p className="mt-1 flex max-w-[85%] items-start gap-1 text-xs text-ink-500" title="How this follow-up was understood">
                            <CornerDownRight className="mt-px size-3 shrink-0" aria-hidden />
                            Searched as: {turn.answer!.standalone_question}
                          </p>
                        )}
                      </div>
                    )}
                    {turn.answer && <AnswerView answer={turn.answer} selected={selected} onSelect={(c) => setSelected(c)} />}
                    {turn.error && <Alert>{turn.error}</Alert>}
                    {!turn.answer && !turn.error && <Working elapsed={elapsed} />}
                  </div>
                );
              })}
            </div>
            <div ref={bottom} />
          </div>
        </div>

        <form
          className="border-t border-ink-200 bg-surface px-6 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(question);
          }}
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-ink-200 bg-surface p-2 shadow-sm focus-within:border-brand-300">
            <label htmlFor="question" className="sr-only">
              Your question
            </label>
            <textarea
              id="question"
              ref={input}
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
              disabled={loading}
              placeholder={turns.length ? "Ask a follow-up…" : "Ask a question about your documents…"}
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-ink-400"
            />
            <button
              type="submit"
              disabled={busy || loading || question.trim().length < 3}
              className="flex size-9 items-center justify-center rounded-xl bg-brand-600 text-white hover:bg-accent-hover disabled:bg-ink-200"
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
    <div className="rounded-2xl border border-ink-200 bg-surface p-4" aria-live="polite">
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
