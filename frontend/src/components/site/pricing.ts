import { DEMO_MAIL } from "@/components/site/links";

/**
 * Plans, for `/pricing` and the pricing teaser on each product page. The same three plans apply to Cyte Legal QA
 * and Cyte Medical QA; a plan covers one product or both. There are no list prices during early access: `price`
 * is what the card shows until the business publishes numbers (put them here, nowhere else).
 */
export interface Plan {
  id: "pilot" | "organization" | "enterprise";
  name: string;
  audience: string;
  price: string;
  billing: string;
  body: string;
  products: string;
  workspaces: string;
  highlights: string[];
  cta: { href: string; label: string };
  featured?: boolean;
}

export const PLANS: Plan[] = [
  {
    id: "pilot",
    name: "Pilot",
    audience: "One team, your documents",
    price: "Set with you",
    billing: "Monthly, for the length of the pilot",
    body: "Try Cyte on your own documents with a small group, with our team on hand to help you set it up.",
    products: "Legal QA or Medical QA",
    workspaces: "One workspace",
    highlights: ["Guided setup on your documents", "Every feature of the product", "Email support"],
    cta: { href: "/contact", label: "Start a pilot" },
  },
  {
    id: "organization",
    name: "Organization",
    audience: "Firms, hospitals and practices",
    price: "Annual agreement",
    billing: "Annual",
    body: "Roll Cyte out across teams, with a separate workspace and admin for each, and direct help from our team.",
    products: "Legal QA, Medical QA, or both",
    workspaces: "A workspace for each team",
    highlights: ["Everything in Pilot", "Rollout help for admins", "One admin per workspace"],
    cta: { href: DEMO_MAIL, label: "Contact sales" },
    featured: true,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    audience: "Your own hosting and data terms",
    price: "Contact sales",
    billing: "Annual, terms agreed with you",
    body: "For organizations that need hosting, data processing terms or an AI provider agreed in writing before records are uploaded.",
    products: "Legal QA, Medical QA, or both",
    workspaces: "A workspace for each team",
    highlights: ["Everything in Organization", "Hosting and data agreements", "Your own AI provider, on request", "Help with your security review"],
    cta: { href: DEMO_MAIL, label: "Contact sales" },
  },
];

/** Included in every plan: the full product. */
export const INCLUDED = [
  "Verified answers with page and clause citations",
  "Ten checks on every sentence, and refusals instead of guesses",
  "Private chats with follow-up questions",
  "Library with private, shared and workspace documents",
  "Organization, workspaces and three roles",
  "Invite codes with approval by a person",
  "Member profiles and usage counts for admins",
  "Hash-chained audit trail with filters and verification",
];
