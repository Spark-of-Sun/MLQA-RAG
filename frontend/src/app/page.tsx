import { BadgeCheck, Ban, Building2, FileSearch, Lock, ScrollText } from "lucide-react";

import { Logo } from "@/components/logo";
import { auth0 } from "@/lib/auth0";

const FEATURES = [
  {
    icon: BadgeCheck,
    title: "Every sentence is verified",
    body: "Each claim must quote its source. Quotes, numbers, dates and dosages are checked against the cited passage before anything is shown.",
  },
  {
    icon: Ban,
    title: "Refuses instead of guessing",
    body: "When the documents do not support an answer, you get a clear refusal, not a confident hallucination.",
  },
  {
    icon: FileSearch,
    title: "Page- and clause-level citations",
    body: "Click any citation to see the exact highlighted passage, with document, section and page.",
  },
  {
    icon: Lock,
    title: "Isolation in the database",
    body: "Workspaces are separated by PostgreSQL row-level security. Private documents stay private, even from admins.",
  },
  {
    icon: Building2,
    title: "Built for firms and hospitals",
    body: "Organizations, admin-approved workspaces and members, joined with one-time codes and approvals.",
  },
  {
    icon: ScrollText,
    title: "Tamper-evident audit trail",
    body: "Every upload, approval and answer is written to a hash-chained log that detects any later edit.",
  },
];

const AUTH_ERRORS: Record<string, string> = {
  invalid_state: "That sign-in link was already used or has expired. Please sign in again.",
  missing_state: "That sign-in link was already used or has expired. Please sign in again.",
  access_denied: "Auth0 refused the sign-in. If this repeats, check that the API identifier matches AUTH0_AUDIENCE_MAIN.",
};

export default async function Landing({ searchParams }: { searchParams: Promise<{ auth_error?: string }> }) {
  const session = await auth0.getSession();
  const { auth_error: authError } = await searchParams;
  return (
    <div className="min-h-full bg-white">
      {authError && (
        <div role="alert" className="border-b border-amber-200 bg-amber-50 px-6 py-3 text-center text-sm text-amber-900">
          {AUTH_ERRORS[authError] ?? `Sign-in did not complete (${authError}). Please try again.`}{" "}
          <a href="/auth/login" className="font-semibold underline">
            Sign in
          </a>
        </div>
      )}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Logo size="lg" />
        <nav className="flex items-center gap-2">
          {session ? (
            <a href="/home" className="rounded-lg bg-ink-900 px-4 py-2 text-sm font-medium text-white hover:bg-ink-800">
              Open workspace
            </a>
          ) : (
            <>
              <a href="/auth/login" className="rounded-lg px-4 py-2 text-sm font-medium text-ink-700 hover:bg-ink-100">
                Sign in
              </a>
              <a
                href="/auth/login?screen_hint=signup"
                className="rounded-lg bg-ink-900 px-4 py-2 text-sm font-medium text-white hover:bg-ink-800"
              >
                Get started
              </a>
            </>
          )}
        </nav>
      </header>

      <section className="mx-auto max-w-6xl px-6 pt-16 pb-20">
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-ink-200 px-3 py-1 text-xs font-medium text-ink-600">
          <span className="size-1.5 rounded-full bg-emerald-500" /> For legal and clinical teams
        </p>
        <h1 className="max-w-3xl text-5xl font-semibold tracking-tight text-ink-950">
          Answers you can cite. <span className="text-ink-400">Or no answer at all.</span>
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-ink-600">
          Ask questions across contracts, case files, drug labels and clinical documents. Every sentence comes with a
          machine-verified citation to the page and clause it came from, and unsupported claims are removed before you
          see them.
        </p>
        <div className="mt-8 flex gap-3">
          <a
            href={session ? "/home" : "/auth/login?screen_hint=signup"}
            className="rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
          >
            {session ? "Open workspace" : "Create your organization"}
          </a>
          {!session && (
            <a href="/auth/login" className="rounded-lg border border-ink-200 px-5 py-3 text-sm font-semibold text-ink-800 hover:bg-ink-50">
              I have an invite code
            </a>
          )}
        </div>

        <div className="mt-16 rounded-2xl border border-ink-200 bg-ink-50 p-6">
          <p className="text-xs font-medium tracking-wide text-ink-500 uppercase">Example</p>
          <p className="mt-3 font-medium text-ink-900">When must the severance benefit be paid?</p>
          <p className="mt-2 text-ink-700">
            The severance benefit must be paid no later than thirty (30) days following the Separation Date.
            <sup className="ml-0.5 rounded bg-brand-100 px-1 text-xs font-semibold text-brand-700">1</sup> It cannot be
            paid before the Release becomes effective.
            <sup className="ml-0.5 rounded bg-brand-100 px-1 text-xs font-semibold text-brand-700">1</sup>
          </p>
          <p className="mt-3 text-xs text-ink-500">
            [1] Separation and Release Agreement · §3 Severance Benefit — “
            <mark className="cite">shall be paid no later than thirty (30) days following the Separation Date</mark>”
          </p>
        </div>
      </section>

      <section className="border-t border-ink-100 bg-ink-50/60">
        <div className="mx-auto grid max-w-6xl gap-6 px-6 py-16 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="rounded-xl border border-ink-200 bg-white p-5">
              <Icon className="size-5 text-brand-600" aria-hidden />
              <h2 className="mt-3 font-semibold text-ink-900">{title}</h2>
              <p className="mt-1 text-sm text-ink-600">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="mx-auto max-w-6xl px-6 py-8 text-xs text-ink-500">
        Surfaces and cites what your documents say. It does not give legal or medical advice.
      </footer>
    </div>
  );
}
