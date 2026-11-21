import { BRAND, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

export const SIGN_UP = "/auth/login?screen_hint=signup";
export const SIGN_IN = "/auth/login";

export function mailto(address: string, subject?: string): string {
  return subject ? `mailto:${address}?subject=${encodeURIComponent(subject)}` : `mailto:${address}`;
}

export const DEMO_MAIL = mailto(CONTACT_EMAIL, `${BRAND} demo request`);
export const SUPPORT_MAIL = mailto(SUPPORT_EMAIL, `${BRAND} support`);

/** Site navigation, shared by the header and the footer. */
export const INDUSTRY_LINKS = [
  { href: "/industries/legal", label: "Legal", body: "Contracts, case files, statutes and regulations" },
  { href: "/industries/healthcare", label: "Healthcare", body: "Drug labels, guidelines, protocols and research" },
];

export const NAV: { href: string; label: string; children?: typeof INDUSTRY_LINKS }[] = [
  { href: "/product", label: "Product" },
  { href: "/industries", label: "Industries", children: INDUSTRY_LINKS },
  { href: "/security", label: "Security" },
  { href: "/pricing", label: "Pricing" },
  { href: "/company", label: "Company" },
];
