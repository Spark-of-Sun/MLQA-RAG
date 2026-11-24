import { BRAND, COMPANY, CONTACT_EMAIL } from "@/lib/format";

/**
 * Website FAQ, grouped. The full list is `/faq`; the homepage, pricing and security pages show a few groups or
 * items from here, so an answer is written once. Every answer must stay true of the product as built
 * (src/lib/docs.ts); product-specific questions live with their product in products.ts.
 */
export interface Faq {
  q: string;
  a: string;
}

export const FAQ: { id: string; title: string; items: Faq[] }[] = [
  {
    id: "product",
    title: "The product",
    items: [
      {
        q: `Does ${BRAND} give legal or medical advice?`,
        a: "No. It reports what your documents say and where they say it. Decisions stay with qualified professionals.",
      },
      {
        q: "What if my documents don't contain the answer?",
        a: `${BRAND} replies “The provided documents do not address this.” If they answer part of the question, you get that part, followed by the same sentence.`,
      },
      {
        q: "How long does an answer take?",
        a: "Most answers arrive in 5 to 20 seconds. Nothing is shown until every sentence has passed its checks.",
      },
      {
        q: "Which files can it read?",
        a: "PDFs with selectable text, Word, HTML, plain text and Markdown, and XML for journal articles (JATS), FDA drug labels (SPL) and US federal regulations (eCFR). Files can be up to 25 MB.",
      },
      {
        q: "Can it read scanned PDFs?",
        a: "Not yet. Scanned pages are reported and skipped, never guessed. Upload PDFs with selectable text, or Word files. Text recognition is on our roadmap.",
      },
    ],
  },
  {
    id: "verification",
    title: "Answers and verification",
    items: [
      {
        q: "How does Cyte check an answer?",
        a: "Every sentence must quote the passage it relies on. Ten checks then confirm, among other things, that the quote appears word for word, that every number and date matches, and that a second, stricter review agrees the passage supports the claim.",
      },
      {
        q: "Why was a sentence removed from my answer?",
        a: "It failed one of the checks, for example a number that does not appear in the cited passage. The answer shows that a claim was removed and why; the rest is still verified.",
      },
      {
        q: "Which AI model writes the answers?",
        a: `${BRAND} works with several model providers. Whichever model drafts the answer, every sentence goes through the same checks, and the model used is shown in the answer's verification details.`,
      },
      {
        q: "Does it answer from general knowledge?",
        a: "No. Answers come only from the documents you are allowed to read: your own, those shared with you, and those shared with your whole workspace.",
      },
    ],
  },
  {
    id: "security",
    title: "Security and privacy",
    items: [
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
        q: "Is Cyte certified (SOC 2, ISO 27001, HIPAA)?",
        a: `Not yet. No external audit, certification or penetration test has been completed. ${BRAND} is designed for privileged and clinical documents, and we describe its controls plainly on the Security page.`,
      },
    ],
  },
  {
    id: "buying",
    title: "Plans and getting started",
    items: [
      {
        q: "How do we start?",
        a: "Create an organization and invite your team today, or book a demo and we will show Cyte on public documents like yours and set up a pilot with you.",
      },
      {
        q: "Why are there no list prices?",
        a: `${BRAND} is in early access. We agree the price with each early customer and confirm it in writing before you commit.`,
      },
      {
        q: "Can we pay monthly or annually?",
        a: "Organization plans are annual agreements. A pilot's length and billing, including month to month, are set with you before it starts.",
      },
      {
        q: "Can we use both products?",
        a: `Yes. ${BRAND} Legal QA and ${BRAND} Medical QA can run in the same organization, each team in its own workspace.`,
      },
      {
        q: "Who do we contact?",
        a: `Email ${CONTACT_EMAIL} for demos, pilots and plans. Customers can reach support at the address on the Contact page.`,
      },
    ],
  },
];

export function faqGroup(id: string): Faq[] {
  return FAQ.find((g) => g.id === id)?.items ?? [];
}
