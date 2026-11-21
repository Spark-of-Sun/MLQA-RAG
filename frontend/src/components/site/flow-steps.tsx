"use client";

import { CircleCheck, FileText, FileUp, MessageSquareText, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

// "From document to cited answer": four steps that advance on their own, with a progress bar on the active one.
// Clicking a step selects it and pauses the rotation.

const STEPS = [
  {
    title: "Upload",
    body: "Contracts, case files, regulations, drug labels and guidelines. Cyte splits them by section, clause and page.",
    icon: FileUp,
  },
  {
    title: "Ask",
    body: "Plain-language questions, with follow-ups in the same chat, over only the documents you may see.",
    icon: MessageSquareText,
  },
  {
    title: "Verify",
    body: "Each drafted sentence must quote its source and pass ten checks. Anything that fails is removed.",
    icon: ShieldCheck,
  },
  { title: "Cite", body: "You read verified sentences, each linked to its highlighted passage.", icon: FileText },
];

const STEP_MS = 4500;

export function FlowSteps() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setTimeout(() => setActive((a) => (a + 1) % STEPS.length), STEP_MS);
    return () => clearTimeout(t);
  }, [active, paused]);

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_1.1fr]">
      <ol className="border-t border-ink-200" role="tablist" aria-label="How it works">
        {STEPS.map((s, i) => {
          const on = i === active;
          return (
            <li key={s.title} className="relative border-b border-ink-200">
              <button
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => {
                  setActive(i);
                  setPaused(true);
                }}
                className="flex w-full items-start gap-5 py-5 text-left"
              >
                <span className={`font-mono text-xs transition-colors ${on ? "text-ink-950" : "text-ink-400"}`}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span>
                  <span className={`block text-lg font-semibold transition-colors ${on ? "text-ink-950" : "text-ink-400"}`}>
                    {s.title}
                  </span>
                  <span
                    className={`grid text-sm leading-6 text-ink-600 transition-all duration-500 ${on ? "mt-1 grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}
                  >
                    <span className="overflow-hidden">{s.body}</span>
                  </span>
                </span>
              </button>
              {on && (
                <span className="absolute inset-x-0 -bottom-px h-0.5 bg-ink-100">
                  <span
                    key={`${i}-${paused}`}
                    className={`block h-full bg-ink-950 ${paused ? "" : "fill"}`}
                    style={{ ["--t" as string]: `${STEP_MS}ms` }}
                  />
                </span>
              )}
            </li>
          );
        })}
      </ol>
      <div className="relative min-h-72 overflow-hidden rounded-3xl border border-ink-200 bg-white p-6" aria-hidden>
        <Panel step={active} />
      </div>
    </div>
  );
}

function Panel({ step }: { step: number }) {
  if (step === 0) {
    const files = [
      ["Separation Agreement.pdf", "12 pages · 38 passages"],
      ["Lisinopril label.xml", "FDA drug label · 64 passages"],
      ["21 CFR Part 11.xml", "eCFR · 41 passages"],
    ];
    return (
      <div key="upload" className="space-y-3">
        {files.map(([name, meta], i) => (
          <div key={name} className="slide-in rounded-xl border border-ink-200 p-3" style={{ animationDelay: `${i * 180}ms` }}>
            <div className="flex items-center gap-2 text-sm font-medium text-ink-900">
              <FileText className="size-4 text-ink-500" /> {name}
              <span className="ml-auto rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">ready</span>
            </div>
            <p className="mt-1 text-xs text-ink-500">{meta}</p>
            <div className="mt-2 h-1 overflow-hidden rounded bg-ink-100">
              <div className="fill h-full bg-ink-900" style={{ ["--t" as string]: `${900 + i * 300}ms` }} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (step === 1) {
    return (
      <div key="ask" className="space-y-3">
        <p className="slide-in ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-md bg-ink-900 px-4 py-2 text-sm text-white">
          When must the severance benefit be paid?
        </p>
        <p
          className="slide-in ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-md bg-ink-900 px-4 py-2 text-sm text-white"
          style={{ animationDelay: "700ms" }}
        >
          And what must the Executive sign first?
        </p>
        <p className="slide-in text-right text-xs text-ink-500" style={{ animationDelay: "1200ms" }}>
          ↳ Searched as: What must the Executive sign before the severance benefit is paid?
        </p>
      </div>
    );
  }
  if (step === 2) {
    const checks = ["Quote found in source", "Numbers and dates match", "Wording supported", "Source entails the claim", "Page and section"];
    return (
      <ul key="verify" className="space-y-2.5">
        {checks.map((c, i) => (
          <li key={c} className="slide-in flex items-center gap-2 text-sm text-ink-700" style={{ animationDelay: `${i * 260}ms` }}>
            <CircleCheck className="size-4 text-emerald-600" /> {c}
          </li>
        ))}
        <li className="slide-in rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800" style={{ animationDelay: "1500ms" }}>
          A claim could not be verified and was removed. (number not in the cited passage)
        </li>
      </ul>
    );
  }
  return (
    <div key="cite" className="slide-in">
      <p className="text-sm leading-6 text-ink-800">
        The severance benefit must be paid no later than thirty (30) days following the Separation Date.
        <sup className="ml-0.5 rounded bg-brand-600 px-1 text-[10px] font-semibold text-white">1</sup>
      </p>
      <div className="mt-4 rounded-xl border border-ink-200 bg-ink-50 p-4">
        <p className="text-[11px] font-medium text-brand-700">Source 1 · §3 Severance Benefit · p. 2</p>
        <p className="mt-2 text-xs leading-5 text-ink-600">
          …the Severance Benefit{" "}
          <mark className="cite sheen">shall be paid no later than thirty (30) days following the Separation Date</mark>, in a single
          lump sum…
        </p>
      </div>
    </div>
  );
}
