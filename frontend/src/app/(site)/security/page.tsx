import { Ban, Database, EyeOff, Fingerprint, KeyRound, Lock, ScrollText, ShieldCheck, UserCheck } from "lucide-react";
import type { Metadata } from "next";

import { ButtonLink, Container, Label, PointGrid, Questions, Section } from "@/components/site/blocks";
import { faqGroup } from "@/components/site/faq";
import { SECURITY_MAIL } from "@/components/site/links";
import { pageMeta } from "@/components/site/seo";
import { BRAND, CONTACT_EMAIL } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "Security",
  `How ${BRAND} keeps each team's documents, chats and answers apart: database isolation, private-by-default sharing, secure sign-in and a verifiable audit trail.`,
  "/security",
);

const CONTROLS = [
  {
    icon: Database,
    title: "Isolation in the database",
    body: "PostgreSQL row-level security decides what each person may read, for every document, passage, answer and share. It fails closed.",
  },
  { icon: Lock, title: "Separate workspaces", body: "Each team's workspace is invisible to the others, including to other admins." },
  {
    icon: EyeOff,
    title: "Owner kept out of content",
    body: "The Super Admin governs the organization but has no route and no database policy for documents, members' details or questions.",
  },
  { icon: Fingerprint, title: "Private by default", body: "A member's uploads and chats are theirs alone until they choose to share a document." },
  {
    icon: KeyRound,
    title: "Codes and approvals",
    body: "Invite codes are shown once, stored only as keyed hashes, limited by expiry and uses, and can be rotated at any time. Every join is approved by a person.",
  },
  { icon: UserCheck, title: "Attempt limits", body: "Repeated wrong codes are blocked per person and per network, and every failure gives the same message." },
  {
    icon: ShieldCheck,
    title: "Secure sign-in",
    body: "Sign-in runs through Auth0. Access tokens stay on the server, and every page uses a strict content security policy.",
  },
  { icon: Ban, title: "Instant suspension", body: "Suspending a member or a workspace takes effect on their next request. No data is deleted." },
  {
    icon: ScrollText,
    title: "Verifiable audit",
    body: "Every event is chained to the one before it with SHA-256, and changes are blocked in the database. Anyone can verify the chain.",
  },
];

const NOT_YET = [
  { title: "Per-organization encryption keys", body: "Documents are not yet encrypted with a separate key for each organization." },
  { title: "Passkeys for admins", body: "Admins sign in like everyone else; required passkeys and step-up checks are planned." },
  { title: "Text recognition for scans", body: "Scanned pages are reported and skipped, never guessed." },
  { title: "Independent review", body: "No external penetration test or certification has been completed yet." },
];

// The shared security answers (processing, admins, owner, certification) and the ones only this page needs.
const QUESTIONS = [
  ...faqGroup("security"),
  {
    q: "What does the audit trail record?",
    a: "Who did what and when: joins, approvals, uploads, shares, deletions, chats and answers. Questions and answers are stored as hashes, never as text, and titles of documents a viewer cannot open are hidden.",
  },
  {
    q: "What happens when someone leaves?",
    a: "Their admin suspends them, and access stops on their next request. Their data is kept, not deleted.",
  },
  {
    q: "How long does a session last?",
    a: "Sessions end after 30 minutes without activity, and after 8 hours in any case.",
  },
];

const ROLES: [string, string, string, string][] = [
  ["Read a member's private documents", "No", "No", "Their own only"],
  ["Read someone else's chats", "No", "No", "No"],
  ["See members' profiles and usage counts", "No", "Own workspace", "No"],
  ["Approve and suspend people", "Admins", "Members of own workspace", "No"],
  ["Verify the audit hash chain", "Yes", "Yes", "Yes"],
];

export default function SecurityPage() {
  return (
    <>
      <section className="site-grid border-b border-ink-200">
        <Container className="grid gap-14 pt-16 pb-16 md:pt-24 md:pb-24 lg:grid-cols-[1.2fr_1fr] lg:items-end">
          <div>
            <div className="rise">
              <Label>Security</Label>
            </div>
            <h1 className="rise d-1 mt-6 text-[2.6rem] leading-[1.05] font-medium text-balance text-ink-950 md:text-6xl md:leading-[1.03]">
              Access decided by the database.
            </h1>
            <p className="rise d-2 mt-6 max-w-2xl text-lg leading-8 text-ink-600">
              Every document, passage and answer is checked against who is asking, in PostgreSQL itself, so a mistake in
              one screen cannot expose another team&apos;s work.
            </p>
            <div className="rise d-3 mt-9 flex flex-wrap gap-3">
              <ButtonLink href="/contact">Bring us your security review</ButtonLink>
              <ButtonLink href={SECURITY_MAIL} variant="secondary">
                Report a vulnerability
              </ButtonLink>
            </div>
          </div>
          <div className="rise d-3 rounded-xl border border-ink-200 bg-surface p-6">
            <p className="font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">Where we stand today</p>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-ink-700">
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-brush" aria-hidden />
                Designed for privileged legal and clinical documents.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-brush" aria-hidden />
                No external audit, certification (such as SOC 2 or ISO 27001) or penetration test has been completed yet.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-brush" aria-hidden />
                During early access, document text is sent to Google for search and cited passages to the configured AI
                model. Talk to us before uploading client or patient records.
              </li>
            </ul>
          </div>
        </Container>
      </section>

      <Section label="Controls" title="Controls in place today.">
        <PointGrid items={CONTROLS} />
      </Section>

      <Section tone="muted" label="Roles" title="Who can see what." intro="Three roles with fixed limits. A role can never be raised from inside the product.">
        <div className="overflow-x-auto rounded-xl border border-ink-200 bg-surface">
          <table className="w-full min-w-[40rem] text-sm">
            <caption className="sr-only">What each role can do</caption>
            <thead className="border-b border-ink-200">
              <tr>
                <th scope="col" className="px-5 py-4 text-left font-medium text-ink-500">
                  Task
                </th>
                {["Super Admin", "Admin", "Member"].map((r) => (
                  <th key={r} scope="col" className="px-4 py-4 text-left font-semibold text-ink-950">
                    {r}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-200">
              {ROLES.map(([task, ...cells]) => (
                <tr key={task}>
                  <th scope="row" className="px-5 py-3.5 text-left font-normal text-ink-700">
                    {task}
                  </th>
                  {cells.map((c, i) => (
                    <td key={i} className="px-4 py-3.5 text-ink-900">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section tone="dark" label="Roadmap" title="Not built yet." intro="We describe what Cyte does today, plainly. These are designed but not available now.">
        <PointGrid items={NOT_YET} columns={4} dark />
      </Section>

      <Section label="FAQ" title="Questions reviewers ask." intro={`Security questions, reviews and vulnerability reports: ${CONTACT_EMAIL}.`}>
        <Questions items={QUESTIONS} />
      </Section>
    </>
  );
}
