import { Ban, Database, EyeOff, Fingerprint, KeyRound, Lock, ScrollText, ShieldCheck, UserCheck } from "lucide-react";
import type { Metadata } from "next";

import { ButtonLink, PageHero, PointGrid, Questions, Section } from "@/components/site/blocks";
import { mailto } from "@/components/site/links";
import { BRAND, COMPANY, CONTACT_EMAIL } from "@/lib/format";

export const metadata: Metadata = {
  title: "Security",
  description: `How ${BRAND} keeps each team's documents, chats and answers apart.`,
};

const SECURITY_MAIL = mailto(CONTACT_EMAIL, `${BRAND} security`);

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

const QUESTIONS = [
  {
    q: "Where is my data processed?",
    a: `During early access, ${BRAND} is hosted by ${COMPANY}. Document text is sent to Google to make it searchable, and the passages behind each question are sent to the configured AI model to draft the answer. Before you upload real client or patient records, talk to us about hosting and data agreements.`,
  },
  {
    q: "Can an admin read a member's documents or chats?",
    a: "Chats, never. Documents, only those the member chose to share with the admin. The admin sees counts, such as how many private documents a member has, but not their content.",
  },
  {
    q: "Can the organization owner read workspace content?",
    a: "No. The Super Admin's view is limited to admins, codes, organization events and usage totals. The database returns nothing else for that role, even if asked.",
  },
  {
    q: "What does the audit trail record?",
    a: "Who did what and when: joins, approvals, uploads, shares, deletions, chats and answers. Questions and answers are stored as hashes, never as text, and titles of documents a viewer cannot open are hidden.",
  },
  {
    q: "What happens when someone leaves?",
    a: "Their admin suspends them, and access stops on their next request. Their data is kept, not deleted.",
  },
];

export default function SecurityPage() {
  return (
    <>
      <PageHero
        center
        label="Security"
        title="Access decided by the database."
        intro="Every document, passage and answer is checked against who is asking, in PostgreSQL itself, so a mistake in one screen cannot expose another team's work."
        actions={
          <>
            <ButtonLink href="/contact">Bring us your security review</ButtonLink>
            <ButtonLink href={SECURITY_MAIL} variant="secondary">
              Report a vulnerability
            </ButtonLink>
          </>
        }
      />
      <Section title="Controls in place today.">
        <PointGrid items={CONTROLS} />
      </Section>
      <Section muted title="Not built yet." intro="We describe what Cyte does today, plainly. These are on the roadmap and not available now.">
        <PointGrid items={NOT_YET} columns={4} />
      </Section>
      <Section title="Questions reviewers ask.">
        <Questions items={QUESTIONS} />
      </Section>
    </>
  );
}
