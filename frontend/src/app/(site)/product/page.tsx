import { ArrowRight, Building2, Check, Minus, UserCog, Users, X } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { AnswerCard, ButtonLink, NumberedGrid, PageHero, PointGrid, Questions, Section } from "@/components/site/blocks";
import { VerificationChecks } from "@/components/site/checks";
import { SIGN_UP } from "@/components/site/links";
import { faqGroup } from "@/components/site/faq";
import { PRODUCTS } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "Products",
  `${BRAND} Legal QA and ${BRAND} Medical QA: how Cyte turns your documents into verified, cited answers.`,
  "/product",
);

const ASK = [
  { title: "Ask in plain language", body: "Type a question as you would ask a colleague. Up to 2,000 characters." },
  { title: "Follow up in the same chat", body: "“And what must the Executive sign first?” is understood from the conversation." },
  { title: "See how it was read", body: "A follow-up shows the full question that was searched, so nothing is hidden." },
  { title: "Chats stay yours", body: "Rename, delete and return to chats. Nobody else can read them, not even your admin." },
];

const LIBRARY = [
  { title: "Private by default", body: "A member's uploads are visible only to them until they choose to share." },
  { title: "Share with your admin", body: "Members tick one box to let their admin search a document." },
  { title: "Share with chosen people", body: "Admins share with the whole workspace or with named members." },
  { title: "Always labelled", body: "Every document shows who shared it and with whom: by you, by your admin or by a member." },
  {
    title: "Formats you already have",
    body: "PDF with selectable text, Word, HTML, plain text, and XML for journal articles (JATS), FDA drug labels (SPL) and US regulations (eCFR).",
  },
  { title: "Split the way documents are written", body: "Passages follow headings, sections, clauses and pages, so citations land in the right place." },
];

const ROLES = [
  {
    icon: Building2,
    title: "Super Admin",
    body: "Creates the organization, invites and approves admins, sees usage totals. Never sees documents or questions.",
  },
  {
    icon: UserCog,
    title: "Admin",
    body: "Runs one workspace. Invites and approves members, shares documents, sees each member's profile and usage counts.",
  },
  { icon: Users, title: "Member", body: "Asks questions in private chats, uploads documents, and decides what to share with their admin." },
];

const AUDIT = [
  { title: "Sections per role", body: "Members see their library and chats; admins see members, library, questions and codes." },
  { title: "Filters", body: "Filter by event, person and dates, or search. Views are kept in the link, so you can bookmark them." },
  { title: "Verify in one click", body: "Recompute the whole hash chain and see that nothing was changed or removed." },
  { title: "Content stays private", body: "Questions and answers are recorded as hashes, and hidden document titles stay hidden." },
];

type Mark = "yes" | "no" | "partly";
const COMPARISON: { row: string; cyte: Mark; chatbot: Mark; search: Mark }[] = [
  { row: "Answers questions in plain language", cyte: "yes", chatbot: "yes", search: "no" },
  { row: "Uses only your documents", cyte: "yes", chatbot: "partly", search: "yes" },
  { row: "Cites page and section for every sentence", cyte: "yes", chatbot: "partly", search: "no" },
  { row: "Checks each sentence against its source before showing it", cyte: "yes", chatbot: "no", search: "no" },
  { row: "Says so when the documents do not answer", cyte: "yes", chatbot: "partly", search: "no" },
  { row: "Separate workspaces and private documents per person", cyte: "yes", chatbot: "partly", search: "partly" },
  { row: "Tamper-evident audit trail", cyte: "yes", chatbot: "no", search: "no" },
];

function MarkCell({ m }: { m: Mark }) {
  if (m === "yes") return <Check className="mx-auto size-5 text-ink-950" aria-label="Yes" />;
  if (m === "no") return <X className="mx-auto size-5 text-ink-300" aria-label="No" />;
  return <Minus className="mx-auto size-5 text-ink-400" aria-label="Partly, or depends on the product" />;
}

const QUESTIONS = [...faqGroup("product"), ...faqGroup("verification")];

export default function ProductPage() {
  return (
    <>
      <PageHero
        label="Products"
        title="Search, draft and check. In one step."
        intro={`${BRAND} reads your documents, drafts an answer, and checks every sentence against the passage it cites. Choose ${BRAND} Legal QA, ${BRAND} Medical QA, or both. You see only what passed.`}
        actions={
          <>
            <ButtonLink href="/contact">
              Book a demo <ArrowRight className="size-4" aria-hidden />
            </ButtonLink>
            <ButtonLink href={SIGN_UP} variant="secondary">
              Create your organization
            </ButtonLink>
          </>
        }
        aside={PRODUCTS[1] && <AnswerCard sample={PRODUCTS[1].sample} />}
      />

      <Section label="Choose" title="Choose your product." intro="Both products run on the same verification engine. Pick the one built for your documents, or run both in the same organization.">
        <div className="grid gap-6 lg:grid-cols-2">
          {PRODUCTS.map((p) => (
            <Link
              key={p.slug}
              href={`/products/${p.slug}`}
              className="group rounded-xl border border-ink-200 bg-surface p-8 transition-colors hover:border-ink-950 md:p-10"
            >
              <p className="font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">{p.who}</p>
              <h3 className="display mt-6 text-3xl font-medium text-ink-950 md:text-4xl">{p.fullName}</h3>
              <p className="mt-3 text-ink-600">{p.intro}</p>
              <ul className="mt-6 flex flex-wrap gap-2">
                {p.documents.map((d) => (
                  <li key={d} className="rounded-md border border-ink-200 bg-page px-2.5 py-1 text-xs text-ink-600">
                    {d}
                  </li>
                ))}
              </ul>
              <p className="mt-8 flex items-center gap-2 text-sm font-medium text-ink-950">
                Explore {p.fullName} <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </p>
            </Link>
          ))}
        </div>
      </Section>

      <Section
        id="verification"
        tone="muted"
        label="Verification"
        title="Ten checks on every sentence."
        intro="A drafted sentence must quote its source. Before you see it, it has to pass all of these. If one fails, the sentence is removed and the answer says so."
      >
        <VerificationChecks />
      </Section>

      <Section id="chat" label="Ask" title="Ask like you talk to a colleague." intro="Chats work like any chat app, with one difference: every answer is checked against your documents.">
        <PointGrid items={ASK} columns={4} />
      </Section>

      <Section id="library" tone="muted" label="Library" title="A library with clear sharing." intro="Everyone can see at a glance who can use each document.">
        <PointGrid items={LIBRARY} />
      </Section>

      <Section id="teams" label="Teams" title="Built around your teams." intro="One organization, a separate workspace for each team, and people who join with one-time codes and a person's approval.">
        <PointGrid items={ROLES} />
      </Section>

      <Section id="audit" tone="muted" label="Audit" title="An audit trail you can verify." intro="Every upload, approval, share and answer is chained to the event before it with SHA-256.">
        <NumberedGrid items={AUDIT} />
      </Section>

      <Section id="compare" label="Compare" title="Why not a chatbot, or plain search?" intro="Chatbots are fast but hard to check. Search is checkable but slow. Cyte gives you the speed of one with the proof of the other.">
        <div className="overflow-x-auto rounded-xl border border-ink-200 bg-surface">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="border-b border-ink-200 text-ink-600">
              <tr>
                <th className="px-5 py-3 text-left font-medium" />
                <th className="px-4 py-3 font-semibold text-ink-950">{BRAND}</th>
                <th className="px-4 py-3 font-medium">General AI chatbot</th>
                <th className="px-4 py-3 font-medium">Keyword search</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {COMPARISON.map((r) => (
                <tr key={r.row}>
                  <td className="px-5 py-3 text-ink-700">{r.row}</td>
                  <td className="bg-page-muted px-4 py-3">
                    <MarkCell m={r.cyte} />
                  </td>
                  <td className="px-4 py-3">
                    <MarkCell m={r.chatbot} />
                  </td>
                  <td className="px-4 py-3">
                    <MarkCell m={r.search} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-ink-500">A dash means partly, or that it depends on the product and its settings.</p>
      </Section>

      <Section tone="muted" label="FAQ" title="Questions.">
        <Questions items={QUESTIONS} />
      </Section>
    </>
  );
}
