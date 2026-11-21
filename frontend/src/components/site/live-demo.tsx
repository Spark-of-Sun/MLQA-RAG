"use client";

import { Ban, CircleCheck, FileText, Search, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

// An animated illustration of the Ask flow: the question is typed, passages are searched, each sentence is checked,
// and the answer appears with its highlighted source. It loops through a legal, a medical and a refusal example.

interface Scenario {
  question: string;
  answer: string[] | null; // null: the documents do not answer
  source?: { title: string; where: string; before: string; mark: string; after: string };
}

const SCENARIOS: Scenario[] = [
  {
    question: "When must the severance benefit be paid?",
    answer: [
      "The severance benefit must be paid no later than thirty (30) days following the Separation Date.",
      "It is paid only after the Release becomes effective.",
    ],
    source: {
      title: "Separation and Release Agreement",
      where: "§3 Severance Benefit · p. 2",
      before: "…subject to the Release becoming effective, the Severance Benefit ",
      mark: "shall be paid no later than thirty (30) days following the Separation Date",
      after: ", in a single lump sum…",
    },
  },
  {
    question: "What is the recommended starting dose for hypertension?",
    answer: ["The recommended initial dose for hypertension is 10 mg once a day."],
    source: {
      title: "Lisinopril tablets · drug label",
      where: "2.1 Hypertension",
      before: "Initial Therapy: In patients with uncomplicated essential hypertension not on diuretic therapy, ",
      mark: "the recommended initial dose is 10 mg once a day",
      after: ". Dosage should be adjusted according to blood pressure response…",
    },
  },
  {
    question: "Which court has jurisdiction over disputes under the lease?",
    answer: null,
  },
];

const CHECKS = [
  "Citation format",
  "Source retrieved",
  "Source unchanged",
  "Sentence cited",
  "Quote found",
  "Numbers and dates",
  "Wording supported",
  "Source entails claim",
  "Refusal wording",
  "Page and section",
];

type Phase = "typing" | "searching" | "checking" | "answer";
const PHASES: { key: Phase; label: string }[] = [
  { key: "typing", label: "Ask" },
  { key: "searching", label: "Search" },
  { key: "checking", label: "Verify" },
  { key: "answer", label: "Cite" },
];
const DURATION: Record<Exclude<Phase, "typing">, number> = { searching: 1100, checking: 1900, answer: 4200 };

export function LiveDemo() {
  const [n, setN] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const [typed, setTyped] = useState(0);
  const [checks, setChecks] = useState(0);
  const [still, setStill] = useState(false);
  const s = SCENARIOS[n % SCENARIOS.length]!;

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setStill(true);
      setTyped(SCENARIOS[0]!.question.length);
      setChecks(CHECKS.length);
      setPhase("answer");
    }
  }, []);

  useEffect(() => {
    if (still) return;
    let t: ReturnType<typeof setTimeout>;
    if (phase === "typing") {
      if (typed < s.question.length) t = setTimeout(() => setTyped((c) => c + 1), 32);
      else t = setTimeout(() => setPhase("searching"), 350);
    } else if (phase === "searching") {
      t = setTimeout(() => setPhase("checking"), DURATION.searching);
    } else if (phase === "checking") {
      if (checks < CHECKS.length) t = setTimeout(() => setChecks((c) => c + 1), DURATION.checking / CHECKS.length);
      else t = setTimeout(() => setPhase("answer"), 250);
    } else {
      t = setTimeout(() => {
        setN((x) => x + 1);
        setTyped(0);
        setChecks(0);
        setPhase("typing");
      }, DURATION.answer);
    }
    return () => clearTimeout(t);
  }, [phase, typed, checks, s.question.length, still]);

  const active = PHASES.findIndex((p) => p.key === phase);
  return (
    <div className="relative">
      <div className="float absolute -inset-6 -z-10 rounded-[2.5rem] bg-gradient-to-br from-brand-100 via-page to-rose-50 blur-2xl" aria-hidden />
      <div
        className="overflow-hidden rounded-2xl border border-ink-200 bg-surface shadow-2xl shadow-black/10 dark:shadow-black/50"
        role="img"
        aria-label="Animated example: a question is asked, passages are searched, every sentence is checked, and the answer is shown with its highlighted source."
      >
        <div className="flex items-center gap-1.5 border-b border-ink-100 bg-ink-50 px-4 py-2.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-ink-200" />
          <span className="size-2.5 rounded-full bg-ink-200" />
          <span className="size-2.5 rounded-full bg-ink-200" />
          <span className="ml-3 rounded-md bg-surface px-3 py-0.5 text-[11px] text-ink-400">onekami.site/chat</span>
        </div>

        <div className="grid min-h-[22rem] md:grid-cols-[1fr_14rem]" aria-hidden>
          <div className="space-y-4 p-5">
            <p className="ml-auto w-fit max-w-[92%] rounded-2xl rounded-br-md bg-inverse px-4 py-2 text-sm text-on-inverse">
              {s.question.slice(0, typed)}
              {phase === "typing" && <span className="caret ml-px inline-block h-4 w-px translate-y-0.5 bg-on-inverse" />}
            </p>

            {phase === "searching" && (
              <div key={`search-${n}`} className="slide-in flex items-center gap-2 rounded-xl border border-ink-200 px-3.5 py-3 text-xs text-ink-600">
                <Search className="size-3.5 text-link" />
                Searching your documents…
                <span className="ml-auto flex gap-1">
                  <span className="dot size-1.5 rounded-full bg-brand-500" />
                  <span className="dot size-1.5 rounded-full bg-brand-500 [animation-delay:0.2s]" />
                  <span className="dot size-1.5 rounded-full bg-brand-500 [animation-delay:0.4s]" />
                </span>
              </div>
            )}

            {phase === "checking" && (
              <div key={`check-${n}`} className="slide-in rounded-xl border border-ink-200 p-3.5">
                <p className="flex items-center gap-2 text-xs font-medium text-ink-700">
                  <ShieldCheck className="size-3.5 text-emerald-600" /> Checking every sentence against its source
                  <span className="ml-auto font-mono text-[11px] text-ink-400">
                    {checks}/{CHECKS.length}
                  </span>
                </p>
                <ul className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {CHECKS.map((c, i) => (
                    <li key={c} className={`flex items-center gap-1.5 text-[11px] ${i < checks ? "text-ink-700" : "text-ink-300"}`}>
                      {i < checks ? (
                        <CircleCheck className="pop size-3 shrink-0 text-emerald-600" />
                      ) : (
                        <span className="size-3 shrink-0 rounded-full border border-ink-200" />
                      )}
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {phase === "answer" && (
              <div key={`answer-${n}`} className="slide-in rounded-xl border border-ink-200 p-4">
                {s.answer ? (
                  <>
                    <p className="text-sm leading-6 text-ink-800">
                      {s.answer.map((sentence, i) => (
                        <span key={i} className="rise" style={{ ["--d" as string]: `${i * 220}ms` }}>
                          {sentence}
                          <sup className={`ml-0.5 rounded px-1 text-[10px] font-semibold ${i === 0 ? "bg-brand-600 text-white" : "bg-brand-100 text-brand-700"}`}>
                            1
                          </sup>{" "}
                        </span>
                      ))}
                    </p>
                    <p className="mt-3 flex items-center gap-1.5 border-t border-ink-100 pt-2.5 text-[11px] text-ink-500">
                      <ShieldCheck className="size-3.5 text-emerald-600" />
                      {s.answer.length} sentence{s.answer.length === 1 ? "" : "s"} verified · 10 checks each
                    </p>
                  </>
                ) : (
                  <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
                    <Ban className="mt-0.5 size-4 shrink-0" />
                    <div>
                      <p className="font-medium">The provided documents do not address this.</p>
                      <p className="mt-0.5 text-xs text-amber-800">No passage supports an answer, so none is given.</p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-ink-100 bg-ink-50/60 p-4 md:border-t-0 md:border-l">
            {phase === "answer" && s.source ? (
              <div key={`source-${n}`} className="slide-in">
                <p className="flex items-center gap-1.5 text-[11px] font-medium text-brand-700">
                  <FileText className="size-3.5" /> Source 1
                </p>
                <p className="mt-1 text-xs font-semibold text-ink-900">{s.source.title}</p>
                <p className="text-[11px] text-ink-500">{s.source.where}</p>
                <p className="mt-3 text-xs leading-5 text-ink-600">
                  {s.source.before}
                  <mark className="cite sheen">{s.source.mark}</mark>
                  {s.source.after}
                </p>
              </div>
            ) : (
              <div className="space-y-2 pt-1">
                <p className="text-[11px] font-medium text-ink-400">Source</p>
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className={`h-2 rounded bg-ink-200/70 ${phase === "searching" ? "animate-pulse" : ""}`} style={{ width: `${90 - i * 14}%` }} />
                ))}
              </div>
            )}
          </div>
        </div>

        <ol className="grid grid-cols-4 border-t border-ink-100" aria-hidden>
          {PHASES.map((p, i) => (
            <li key={p.key} className="relative px-3 py-2.5 text-center">
              <span className={`font-mono text-[10px] tracking-wider uppercase ${i <= active ? "text-ink-900" : "text-ink-300"}`}>
                {String(i + 1).padStart(2, "0")} {p.label}
              </span>
              <span className="absolute inset-x-0 bottom-0 h-0.5 bg-ink-100">
                {i < active && <span className="block h-full bg-ink-900" />}
                {i === active && !still && (
                  <span
                    key={`${n}-${p.key}`}
                    className="fill block h-full bg-ink-900"
                    style={{ ["--t" as string]: `${p.key === "typing" ? s.question.length * 32 + 350 : DURATION[p.key]}ms` }}
                  />
                )}
                {i === active && still && <span className="block h-full bg-ink-900" />}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <p className="mt-3 text-center text-xs text-ink-400">Illustration of the Ask screen with sample documents.</p>
    </div>
  );
}
