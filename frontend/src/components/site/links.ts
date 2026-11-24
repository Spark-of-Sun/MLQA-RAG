import { BookOpen, Building, CircleHelp, Mail, Route, ShieldCheck, Sparkles, type LucideIcon } from "lucide-react";

import { PRODUCTS } from "@/components/site/products";
import { SOLUTIONS } from "@/components/site/solutions";
import { BRAND, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

export const SIGN_UP = "/auth/login?screen_hint=signup";
export const SIGN_IN = "/auth/login";

export function mailto(address: string, subject?: string): string {
  return subject ? `mailto:${address}?subject=${encodeURIComponent(subject)}` : `mailto:${address}`;
}

export const DEMO_MAIL = mailto(CONTACT_EMAIL, `${BRAND} demo request`);
export const SUPPORT_MAIL = mailto(SUPPORT_EMAIL, `${BRAND} support`);
export const SECURITY_MAIL = mailto(CONTACT_EMAIL, `${BRAND} security`);

export interface NavLink {
  href: string;
  label: string;
  body?: string;
  icon?: LucideIcon;
}

/** The two products, as menu and footer links. Derived from products.ts so the IA never drifts from the data. */
export const PRODUCT_LINKS: NavLink[] = PRODUCTS.map((p) => ({
  href: `/products/${p.slug}`,
  label: p.fullName,
  body: p.tagline,
  icon: p.icon,
}));

export const SOLUTION_LINKS: NavLink[] = SOLUTIONS.map((s) => ({
  href: `/solutions/${s.slug}`,
  label: s.name,
  body: s.summary,
  icon: s.icon,
}));

export const RESOURCE_LINKS: NavLink[] = [
  { href: "/docs", label: "Documentation", body: "How to set up, ask, share and audit.", icon: BookOpen },
  { href: "/faq", label: "Help and FAQ", body: "Answers to the questions teams ask first.", icon: CircleHelp },
  { href: "/product#verification", label: "How answers are checked", body: "The ten checks on every sentence.", icon: Sparkles },
  { href: "/docs/roadmap", label: "Not built yet", body: "What is designed but not in this version.", icon: Route },
];

export const COMPANY_LINKS: NavLink[] = [
  { href: "/about", label: "About", body: "Why we build Cyte, and how we work.", icon: Building },
  { href: "/contact", label: "Contact", body: "Sales, support and security.", icon: Mail },
  { href: "/security", label: "Security", body: "How each team's data is kept apart.", icon: ShieldCheck },
];

export interface NavItem {
  href: string;
  label: string;
  /** A menu: a list of links, with an optional footer link. */
  menu?: { links: NavLink[]; wide?: boolean; footer?: NavLink };
}

/** Site navigation for the header (desktop menus and the mobile menu). */
export const NAV: NavItem[] = [
  {
    href: "/product",
    label: "Products",
    menu: { links: PRODUCT_LINKS, footer: { href: "/product", label: "Compare both products" } },
  },
  {
    href: "/solutions",
    label: "Solutions",
    menu: { links: SOLUTION_LINKS, wide: true, footer: { href: "/solutions", label: "All solutions" } },
  },
  { href: "/security", label: "Security" },
  { href: "/pricing", label: "Pricing" },
  { href: "/docs", label: "Resources", menu: { links: RESOURCE_LINKS } },
  { href: "/about", label: "Company", menu: { links: COMPANY_LINKS } },
];

/** Footer columns. */
export const FOOTER: { title: string; links: NavLink[] }[] = [
  {
    title: "Products",
    links: [
      ...PRODUCT_LINKS.map(({ href, label }) => ({ href, label })),
      { href: "/product", label: "Compare products" },
      { href: "/product#verification", label: "How answers are checked" },
      { href: "/pricing", label: "Pricing" },
    ],
  },
  { title: "Solutions", links: SOLUTION_LINKS.map(({ href, label }) => ({ href, label })) },
  {
    title: "Resources",
    links: [
      { href: "/docs", label: "Documentation" },
      { href: "/faq", label: "Help and FAQ" },
      { href: "/docs/troubleshooting", label: "Troubleshooting" },
      { href: "/docs/roadmap", label: "Not built yet" },
      { href: SIGN_IN, label: "Sign in" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: "/about", label: "About" },
      { href: "/contact", label: "Contact" },
      { href: "/security", label: "Security" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/legal/privacy", label: "Privacy notice" },
      { href: "/legal/terms", label: "Terms of use" },
      { href: "/legal/cookies", label: "Cookie notice" },
    ],
  },
];

/** Links that need a full page load (auth routes, mail): plain <a>, not next/link. */
export function isExternal(href: string): boolean {
  return href.startsWith("/auth/") || href.startsWith("mailto:") || href.startsWith("http");
}
