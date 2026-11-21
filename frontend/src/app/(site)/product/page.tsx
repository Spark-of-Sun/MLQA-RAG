import { ArrowRight, Building2, Check, Minus, UserCog, Users, X } from "lucide-react";
import type { Metadata } from "next";

import { ButtonLink, NumberedGrid, PageHero, PointGrid, Questions, Section } from "@/components/site/blocks";
import { SIGN_UP } from "@/components/site/links";
import { LiveDemo } from "@/components/site/live-demo";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = {
  title: "Product",
  description: `How ${BRAND} turns your documents into verified, cited answers.`,
};

const CHECKS = [
  ["Citation format", "The citation points to a real source of this answer."],
  ["Source was retrieved", "The answer cites only passages found for this question."],
  ["Source unchanged", "The passage did not change between search and answer."],
  ["Sentence is cited", "Every sentence that states a fact has a citation."],
  ["Quote found in source", "The supporting quote appears word for word in the passage."],
  ["Numbers and dates match", "Every number, date, amount and dosage appears in the passage."],
  ["Wording supported", "The sentence's key terms come from the passage."],
  ["Source entails the claim", "A second, stricter review confirms the passage supports the claim."],
  ["Refusal wording", "A “does not address” reply is exact and stands alone."],
  ["Resolves to page and section", "The citation leads to a real place in the document."],
];

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

const QUESTIONS = [
  { q: "Does Cyte give legal or medical advice?", a: "No. It reports what your documents say and where. Decisions stay with qualified professionals." },
  {
    q: "What if my documents don't contain the answer?",
    a: "Cyte replies “The provided documents do not address this.” If they answer part of the question, you get that part, followed by the same sentence.",
  },
  {
    q: "Why was a sentence removed from my answer?",
    a: "It failed one of the checks, for example a number that does not appear in the cited passage. The answer shows that a claim was removed and why; the rest is still verified.",
  },
  {
    q: "Which AI model writes the answers?",
    a: "Cyte works with several model providers. Whichever model drafts the answer, every sentence goes through the same checks, and the model used is shown in the answer's verification details.",
  },
  { q: "Can it read scanned PDFs?", a: "Not yet. Upload PDFs with selectable text, or Word files. Text recognition for scans is on our roadmap." },
];

export default function ProductPage() {
  return (
    <>
      <PageHero
        label="Product"
        title="Search, draft and check. In one step."
        intro={`${BRAND} reads your documents, drafts an answer, and checks every sentence against the passage it cites. You see only what passed.`}
        actions={
          <>
            <ButtonLink href={SIGN_UP}>
              Get started <ArrowRight className="size-4" aria-hidden />
            </ButtonLink>
            <ButtonLink href="/contact" variant="secondary">
              Book a demo
            </ButtonLink>
          </>
        }
        aside={<LiveDemo />}
      />

      <Section
        id="verification"
        title="Ten checks on every sentence."
        intro="A drafted sentence must quote its source. Before you see it, it has to pass all of these. If one fails, the sentence is removed and the answer says so."
      >
        <ol className="grid border-t border-l border-ink-200 sm:grid-cols-2 lg:grid-cols-5">
          {CHECKS.map(([title, body], i) => (
            <li key={title} className="border-r border-b border-ink-200 p-5">
              <span className="font-mono text-xs text-ink-400">{String(i + 1).padStart(2, "0")}</span>
              <h3 className="mt-4 text-sm font-semibold text-ink-950">{title}</h3>
              <p className="mt-1.5 text-xs leading-5 text-ink-600">{body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="chat" muted title="Ask like you talk to a colleague." intro="Chats work like any chat app, with one difference: every answer is checked against your documents.">
        <PointGrid items={ASK} columns={4} />
      </Section>

      <Section id="library" title="A library with clear sharing." intro="Everyone can see at a glance who can use each document.">
        <PointGrid items={LIBRARY} />
      </Section>

      <Section id="teams" muted title="Built around your teams." intro="One organization, a separate workspace for each team, and people who join with one-time codes and a person's approval.">
        <PointGrid items={ROLES} />
      </Section>

      <Section id="audit" title="An audit trail you can verify." intro="Every upload, approval, share and answer is chained to the event before it with SHA-256.">
        <NumberedGrid items={AUDIT} />
      </Section>

      <Section id="compare" muted title="Why not a chatbot, or plain search?" intro="Chatbots are fast but hard to check. Search is checkable but slow. Cyte gives you the speed of one with the proof of the other.">
        <div className="overflow-x-auto rounded-2xl border border-ink-200 bg-white">
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
                  <td className="bg-ink-50 px-4 py-3">
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

      <Section title="Questions.">
        <Questions items={QUESTIONS} />
      </Section>
    </>
  );
}
