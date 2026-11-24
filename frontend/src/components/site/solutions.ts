import {
  Briefcase,
  Building2,
  FlaskConical,
  Hospital,
  Landmark,
  Pill,
  type LucideIcon,
} from "lucide-react";

import type { Point, Product } from "@/components/site/products";

/**
 * Use cases by team, for `/solutions` and `/solutions/[slug]`. Each one points at the product it runs on; product
 * facts (capabilities, documents, verification) come from products.ts and are not repeated here. Keep every claim
 * true of the product as built (src/lib/docs.ts): no matter folders, ethical walls, OCR or integrations yet.
 */
export interface Solution {
  slug: string;
  product: Product["slug"];
  icon: LucideIcon;
  name: string;
  /** One line for menus and cards. */
  summary: string;
  title: string;
  intro: string;
  jobs: Point[];
  questions: string[];
  setup: string;
}

export const SOLUTIONS: Solution[] = [
  {
    slug: "law-firms",
    product: "legal",
    icon: Landmark,
    name: "Law firms",
    summary: "Answer from the case file and the contract, with the clause attached.",
    title: "Research the file, not the internet.",
    intro: "Associates and partners ask questions about the documents of a matter and get answers that quote the clause and page, ready to check and paste into a note.",
    jobs: [
      { title: "Case-file questions", body: "What did the witness statement say about the date of delivery? Every sentence comes back with its page." },
      { title: "Contract review", body: "Find notice periods, termination rights and payment terms across the agreements uploaded to the workspace." },
      { title: "Statutes in the same chat", body: "Upload the acts you rely on and ask about them next to the facts of the case." },
      { title: "One workspace per team", body: "Give each practice group its own workspace. Other teams cannot see its documents or chats." },
    ],
    questions: [
      "What notice is required to terminate the agreement?",
      "Which clause limits the supplier's liability, and what is the cap?",
      "What is the punishment for murder under Section 302?",
    ],
    setup: "One organization for the firm, a workspace for each practice group, and an admin who approves each person who joins.",
  },
  {
    slug: "in-house-legal",
    product: "legal",
    icon: Briefcase,
    name: "In-house legal",
    summary: "Answer the business's contract questions in minutes, with the source.",
    title: "Contract answers the business can rely on.",
    intro: "Legal teams field the same questions about renewals, notice and obligations every week. Cyte answers them from the signed agreement and shows the clause it used.",
    jobs: [
      { title: "Renewals and notice", body: "When does the agreement renew, and how much notice does either side need to give?" },
      { title: "Obligations and conditions", body: "What must happen before a payment is due? Conditions are quoted, not paraphrased." },
      { title: "Policies next to contracts", body: "Keep internal policies in the same workspace and ask about both together." },
      { title: "Private drafts", body: "A lawyer's own uploads stay private until they share them with the admin." },
    ],
    questions: [
      "When does the master services agreement renew, and what notice is needed?",
      "When must the severance benefit be paid, and what conditions apply?",
      "Who must approve a change to the statement of work?",
    ],
    setup: "One workspace for the legal team, with the admin sharing the signed agreements with the whole workspace.",
  },
  {
    slug: "compliance",
    product: "legal",
    icon: Building2,
    name: "Compliance",
    summary: "Cite the regulation, the section and the page in every answer.",
    title: "Regulations, quoted to the section.",
    intro: "Compliance teams need the rule as written. Cyte reads US federal regulations in eCFR XML and your own policies, and answers with the section it quotes.",
    jobs: [
      { title: "Regulations as written", body: "eCFR XML keeps its parts and sections, so a citation points to the exact provision." },
      { title: "Policy against rule", body: "Ask what your policy says and what the regulation says, in one chat, each with its own citation." },
      { title: "A record you can show", body: "Every upload, share and answer is in a hash-chained audit trail that anyone with access can verify." },
      { title: "Refusals you can trust", body: "If neither document addresses the question, Cyte says so instead of filling the gap." },
    ],
    questions: [
      "What records must be retained, and for how long?",
      "Which section defines a covered entity?",
      "What does our policy require before data leaves the organization?",
    ],
    setup: "One workspace for the compliance team; the admin shares the regulations and policies everyone works from.",
  },
  {
    slug: "hospitals",
    product: "medical",
    icon: Hospital,
    name: "Hospitals and clinics",
    summary: "Answer from the unit's own protocols and guidelines, with the section.",
    title: "Your protocols, answered at the point of need.",
    intro: "Clinical teams ask about their own guidelines and protocols in plain language, and see the passage behind every sentence before they act on it.",
    jobs: [
      { title: "Protocols and guidelines", body: "Ask about the steps, thresholds and exceptions in the documents your unit follows." },
      { title: "One workspace per department", body: "Cardiology's protocols are separate from oncology's, and neither can see the other's." },
      { title: "Numbers checked", body: "Doses, intervals and thresholds must appear in the cited passage, or the sentence is removed." },
      { title: "Who asked what, recorded", body: "Each answer is recorded in the audit trail, with the question kept as a hash rather than text." },
    ],
    questions: [
      "What is the escalation threshold for a sepsis screen?",
      "Which patients are excluded from the protocol?",
      "How often must observations be repeated after a dose change?",
    ],
    setup: "One organization for the hospital, a workspace for each department, and documents shared with the whole department by its admin.",
  },
  {
    slug: "pharmacy",
    product: "medical",
    icon: Pill,
    name: "Pharmacy",
    summary: "Doses, contraindications and interactions, traced to the label.",
    title: "Every dose, traced to the label.",
    intro: "Pharmacists ask about dosing, contraindications and adverse reactions, and Cyte answers from the FDA drug labels in the workspace, section by section.",
    jobs: [
      { title: "Labels read by section", body: "SPL drug labels keep their own sections, so a citation reads “2.1 Hypertension”." },
      { title: "Units must match", body: "An amount or unit that does not appear in the label passage is removed from the answer." },
      { title: "Formulary documents too", body: "Upload local policies and formulary notes as PDF, Word or text and ask about them alongside labels." },
      { title: "No general knowledge", body: "If the label is not in your library, Cyte refuses rather than answering from memory." },
    ],
    questions: [
      "What is the recommended starting dose for hypertension?",
      "What are the contraindications?",
      "Which adverse reactions were reported most often?",
    ],
    setup: "One workspace for the pharmacy team, with the labels you use shared with the whole workspace.",
  },
  {
    slug: "research",
    product: "medical",
    icon: FlaskConical,
    name: "Research",
    summary: "Ask across papers and cite the section, not just the PDF.",
    title: "Findings with their section attached.",
    intro: "Research teams ask questions across journal articles and get answers that cite the section of the paper each finding came from.",
    jobs: [
      { title: "Journal structure kept", body: "JATS XML articles keep their headings, so citations point to methods, results or discussion." },
      { title: "PDFs with text", body: "Papers as PDFs with selectable text are split by section and page." },
      { title: "Follow-ups in context", body: "Ask a follow-up and see exactly how it was searched, under your question." },
      { title: "Private reading lists", body: "Each researcher's uploads stay private until they choose to share them." },
    ],
    questions: [
      "Which adverse events were reported in the treatment arm?",
      "What was the primary endpoint, and how was it measured?",
      "Which patients were excluded from the study?",
    ],
    setup: "One workspace per research group; each researcher uploads their own papers and shares what the group needs.",
  },
];

export function getSolution(slug: string): Solution | undefined {
  return SOLUTIONS.find((s) => s.slug === slug);
}
