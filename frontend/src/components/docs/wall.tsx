import { Lock } from "lucide-react";
import Link from "next/link";

import { SIGN_IN } from "@/components/site/links";

export type WallReason = "signed-out" | "inactive" | "role" | "unavailable";

const COPY: Record<WallReason, { title: string; body: (audience: string, role: string) => string }> = {
  "signed-out": {
    title: "Sign in to read this page",
    body: (audience) => `This page is part of the documentation for ${audience}. Sign in with your Cyte account to read it.`,
  },
  inactive: {
    title: "Your account is not active yet",
    body: (audience) =>
      `This page is for ${audience}. It opens once your request to join is approved, or your access is restored.`,
  },
  role: {
    title: "This page is for other roles",
    body: (audience, role) => `This page is for ${audience}. You are signed in as ${role}, so it is not available to you.`,
  },
  unavailable: {
    title: "We could not check your access",
    body: () => "Cyte could not confirm your account just now. Try again in a moment.",
  },
};

/** Shown in place of a page the reader may not open. Rendered on the server; the page's text is never sent. */
export function Wall({ reason, audience, role }: { reason: WallReason; audience: string; role: string }) {
  const copy = COPY[reason];
  return (
    <div className="rounded-2xl border border-ink-200 bg-surface px-6 py-14 text-center shadow-edge">
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-ink-100 text-ink-600">
        <Lock className="size-5" aria-hidden />
      </div>
      <h2 className="mt-5 text-xl font-semibold tracking-tight text-ink-950">{copy.title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-600">{copy.body(audience, role)}</p>
      <div className="mt-7 flex flex-wrap justify-center gap-3">
        {reason === "signed-out" && (
          <a href={SIGN_IN} className="rounded-full bg-inverse px-5 py-2.5 text-sm font-medium text-on-inverse hover:bg-inverse-hover">
            Sign in
          </a>
        )}
        <Link
          href="/docs"
          className="rounded-full border border-ink-300 bg-surface px-5 py-2.5 text-sm font-medium text-ink-900 hover:bg-surface-hover"
        >
          Back to the documentation
        </Link>
      </div>
    </div>
  );
}
