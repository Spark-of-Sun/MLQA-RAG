export interface Industry {
  slug: string;
  name: string;
  who: string;
  title: string;
  intro: string;
  fits: { title: string; body: string }[];
  documents: string[];
  questions: string[];
  example: { title: string; body: string }[];
}

export const INDUSTRIES: Industry[] = [
  {
    slug: "legal",
    name: "Legal",
    who: "Law firms, in-house legal and compliance teams",
    title: "Every answer, with its clause.",
    intro: "Find obligations, deadlines and conditions across contracts and case files, each one linked to the clause it came from.",
    fits: [
      { title: "Quotes you can paste", body: "Every sentence carries the exact words of its source, with section and page." },
      { title: "Deadlines and amounts checked", body: "Dates, periods and sums must appear in the cited clause, or the sentence is removed." },
      { title: "Matters stay apart", body: "Each team works in its own workspace. Other teams cannot see its documents." },
      { title: "Private until shared", body: "An associate's uploads stay private, even from the admin, until they choose to share." },
    ],
    documents: ["Contracts and agreements", "Case files and pleadings", "Statutes and acts", "US federal regulations (eCFR)"],
    questions: [
      "When must the severance benefit be paid, and what conditions apply?",
      "What notice is required to terminate the agreement?",
      "What is the punishment for murder under Section 302?",
    ],
    example: [
      { title: "An associate asks", body: "When must the severance benefit be paid?" },
      { title: "Cyte finds the clause", body: "Only in documents the associate may open." },
      { title: "Each sentence is checked", body: "The 30-day period must appear in the cited passage." },
      { title: "The answer cites §3", body: "One click opens the highlighted clause." },
    ],
  },
  {
    slug: "healthcare",
    name: "Healthcare",
    who: "Hospitals, clinics, pharmacy and research teams",
    title: "Dosages you can trace to the label.",
    intro: "Ask about dosing, contraindications and adverse reactions, and see the exact passage of the label or guideline behind every sentence.",
    fits: [
      { title: "Doses checked against the source", body: "Every number and unit in an answer must appear in the cited passage." },
      { title: "Refuses instead of guessing", body: "If the label or guideline does not say it, Cyte does not say it either." },
      { title: "Teams kept separate", body: "Each department works in its own workspace, invisible to the others." },
      { title: "A record of every answer", body: "Who asked, when, and what was cited, in a tamper-evident audit trail." },
    ],
    documents: ["FDA drug labels (SPL)", "Clinical guidelines and protocols", "Research articles (JATS)", "Policies and procedures"],
    questions: [
      "What is the recommended starting dosage for hypertension?",
      "What are the contraindications?",
      "Which adverse reactions were reported most often?",
    ],
    example: [
      { title: "A pharmacist asks", body: "What is the recommended starting dose?" },
      { title: "Cyte reads the label", body: "Dosage and administration, section by section." },
      { title: "The dose is checked", body: "The amount and unit must match the label exactly." },
      { title: "The answer cites the section", body: "One click opens the highlighted passage." },
    ],
  },
];
