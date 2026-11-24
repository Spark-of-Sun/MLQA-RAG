import { Scale, Stethoscope, type LucideIcon } from "lucide-react";

/**
 * The two named products under the Cyte brand. This is the single source of truth for each product's audience,
 * problems, capabilities, document types, example questions, sample answer, workflow and FAQ; it is used by the
 * header menu, the footer, the products index (`/product`), each product's own page (`/products/legal`,
 * `/products/medical`), the solutions pages, pricing and the homepage.
 *
 * Everything here must stay true of the product as built (see src/lib/docs.ts). Sample answers are illustrations
 * drawn from sample documents and are labelled as such wherever they are shown.
 */

export interface Point {
  title: string;
  body: string;
}

/** A source passage as the citation panel shows it: the highlighted words with a little text either side. */
export interface SamplePassage {
  title: string;
  where: string;
  before: string;
  mark: string;
  after: string;
}

export interface SampleAnswer {
  question: string;
  /** Each sentence of the answer and the number of the source it cites. */
  sentences: { text: string; cite: number }[];
  /** Sources in citation order; the first is shown open in the panel. */
  sources: SamplePassage[];
}

export interface Product {
  slug: "legal" | "medical";
  /** Short name used in nav items, footer links and chips, e.g. "Legal QA". */
  name: string;
  /** Full product name used in page titles and headings, e.g. "Cyte Legal QA". */
  fullName: string;
  icon: LucideIcon;
  /** One line for the Products menu. */
  tagline: string;
  who: string;
  title: string;
  intro: string;
  problems: Point[];
  capabilities: Point[];
  documents: string[];
  questions: string[];
  sample: SampleAnswer;
  /** The workflow, as four short steps. */
  example: Point[];
  faq: { q: string; a: string }[];
}

export const PRODUCTS: Product[] = [
  {
    slug: "legal",
    name: "Legal QA",
    fullName: "Cyte Legal QA",
    icon: Scale,
    tagline: "Cited answers from contracts, case files, statutes and regulations.",
    who: "Law firms, in-house legal and compliance teams",
    title: "Every answer, with its clause.",
    intro: "Find obligations, deadlines and conditions across contracts and case files, each one linked to the clause it came from and checked against it before you read it.",
    problems: [
      {
        title: "Fluent answers you cannot file",
        body: "A general chatbot can summarise a contract, but it cannot show you the clause behind each sentence, so every answer has to be checked by hand.",
      },
      {
        title: "Numbers that drift",
        body: "Notice periods, payment deadlines and caps are exactly where a paraphrase goes wrong. One wrong day count is one too many.",
      },
      {
        title: "Privileged work in shared tools",
        body: "Matter documents need to stay with the people working on them, not in a tool where every user can search everything.",
      },
    ],
    capabilities: [
      { title: "Quotes you can paste", body: "Every sentence carries the exact words of its source, with section and page." },
      { title: "Deadlines and amounts checked", body: "Dates, periods and sums must appear in the cited clause, or the sentence is removed." },
      { title: "Refuses instead of guessing", body: "If the documents do not answer the question, Cyte says “The provided documents do not address this.”" },
      { title: "Follow-ups in the same chat", body: "“And what must the Executive sign first?” is understood from the conversation, and answered from the documents." },
      { title: "Teams stay apart", body: "Each team works in its own workspace. Other teams cannot see its documents, chats or answers." },
      { title: "Private until shared", body: "An associate's uploads stay private, even from the admin, until they choose to share." },
    ],
    documents: ["Contracts and agreements", "Case files and pleadings", "Statutes and acts", "US federal regulations (eCFR)"],
    questions: [
      "When must the severance benefit be paid, and what conditions apply?",
      "What notice is required to terminate the agreement?",
      "What is the punishment for murder under Section 302?",
    ],
    sample: {
      question: "When must the severance benefit be paid, and what conditions apply?",
      sentences: [
        { text: "The severance benefit must be paid no later than thirty (30) days following the Separation Date.", cite: 1 },
        { text: "It is paid only after the Release becomes effective.", cite: 1 },
        { text: "The Release becomes effective once the Executive signs it and does not revoke it within seven (7) days.", cite: 2 },
      ],
      sources: [
        {
          title: "Separation and Release Agreement",
          where: "§3 Severance Benefit · p. 2",
          before: "…subject to the Release becoming effective, the Severance Benefit ",
          mark: "shall be paid no later than thirty (30) days following the Separation Date",
          after: ", in a single lump sum, less applicable withholdings…",
        },
        {
          title: "Separation and Release Agreement",
          where: "§5 General Release · p. 3",
          before: "This Release shall become effective on the eighth day after ",
          mark: "the Executive signs it, provided the Executive does not revoke it within seven (7) days",
          after: "…",
        },
      ],
    },
    example: [
      { title: "An associate asks", body: "When must the severance benefit be paid?" },
      { title: "Cyte Legal QA finds the clause", body: "Only in documents the associate may open." },
      { title: "Each sentence is checked", body: "The 30-day period must appear in the cited passage." },
      { title: "The answer cites §3", body: "One click opens the highlighted clause." },
    ],
    faq: [
      {
        q: "Does Cyte Legal QA give legal advice?",
        a: "No. It reports what your documents say and where they say it. Interpreting them, and advising on them, stays with your lawyers.",
      },
      {
        q: "What happens to past answers if a contract is deleted?",
        a: "The document disappears from search at once. Past answers that cited it stay in the chat, with the source marked as no longer available.",
      },
      {
        q: "Can we keep one matter's documents away from other teams?",
        a: "Yes, by giving the team its own workspace: workspaces cannot see each other. Matter folders inside a workspace, with their own access lists and ethical walls, are designed but not built yet.",
      },
      {
        q: "Which files can we upload?",
        a: "PDFs with selectable text, Word, HTML, plain text, and eCFR XML for US federal regulations, up to 25 MB each. Scanned PDFs are not read yet.",
      },
    ],
  },
  {
    slug: "medical",
    name: "Medical QA",
    fullName: "Cyte Medical QA",
    icon: Stethoscope,
    tagline: "Cited answers from drug labels, clinical guidelines and research.",
    who: "Hospitals, clinics, pharmacy and research teams",
    title: "Dosages you can trace to the label.",
    intro: "Ask about dosing, contraindications and adverse reactions, and see the exact passage of the label or guideline behind every sentence.",
    problems: [
      {
        title: "Long labels, short shifts",
        body: "The answer is in the label or the protocol, but finding the right section takes time nobody has on a ward.",
      },
      {
        title: "A wrong unit is a safety event",
        body: "A model that rounds, converts or invents a dose is not usable at the bedside, however confident it sounds.",
      },
      {
        title: "Departments with their own rules",
        body: "Each unit keeps its own protocols. Answers should come from that unit's documents, not from everyone's.",
      },
    ],
    capabilities: [
      { title: "Doses checked against the source", body: "Every number and unit in an answer must appear in the cited passage." },
      { title: "Refuses instead of guessing", body: "If the label or guideline does not say it, Cyte does not say it either." },
      { title: "Reads labels by section", body: "FDA drug labels (SPL) are split by their own sections, so a citation lands on “2.1 Hypertension”, not on page 14." },
      { title: "Research with its structure", body: "Journal articles in JATS XML keep their headings, so citations point to methods, results or discussion." },
      { title: "Departments kept separate", body: "Each department works in its own workspace, invisible to the others." },
      { title: "A record of every answer", body: "Who asked, when, and what was cited, in a tamper-evident audit trail. Questions are stored as hashes, not text." },
    ],
    documents: ["FDA drug labels (SPL)", "Clinical guidelines and protocols", "Research articles (JATS)", "Policies and procedures"],
    questions: [
      "What is the recommended starting dosage for hypertension?",
      "What are the contraindications?",
      "Which adverse reactions were reported most often?",
    ],
    sample: {
      question: "What is the recommended starting dose for hypertension?",
      sentences: [
        {
          text: "In patients with uncomplicated essential hypertension not on diuretic therapy, the recommended initial dose is 10 mg once a day.",
          cite: 1,
        },
        { text: "The dosage should then be adjusted according to blood pressure response.", cite: 1 },
      ],
      sources: [
        {
          title: "Lisinopril tablets · drug label",
          where: "2.1 Hypertension",
          before: "Initial Therapy: ",
          mark: "In patients with uncomplicated essential hypertension not on diuretic therapy, the recommended initial dose is 10 mg once a day",
          after: ". Dosage should be adjusted according to blood pressure response…",
        },
      ],
    },
    example: [
      { title: "A pharmacist asks", body: "What is the recommended starting dose?" },
      { title: "Cyte Medical QA reads the label", body: "Dosage and administration, section by section." },
      { title: "The dose is checked", body: "The amount and unit must match the label exactly." },
      { title: "The answer cites the section", body: "One click opens the highlighted passage." },
    ],
    faq: [
      {
        q: "Does Cyte Medical QA give medical advice?",
        a: "No. It reports what your labels, guidelines and research say, and where. Clinical decisions stay with qualified professionals.",
      },
      {
        q: "Can we upload patient records?",
        a: "Talk to us first. During early access, document text is sent to Google to make it searchable and the cited passages go to the configured AI model. Before you upload patient records we agree hosting and data terms with you.",
      },
      {
        q: "Does it know drugs that are not in our documents?",
        a: "No, by design. Cyte answers only from documents your team has uploaded. If a label is not in your library, the answer is a refusal, not general knowledge.",
      },
      {
        q: "Which files can we upload?",
        a: "FDA drug labels (SPL XML), journal articles (JATS XML), PDFs with selectable text, Word, HTML and plain text, up to 25 MB each. Scanned PDFs are not read yet.",
      },
    ],
  },
];

export function getProduct(slug: string): Product | undefined {
  return PRODUCTS.find((p) => p.slug === slug);
}
