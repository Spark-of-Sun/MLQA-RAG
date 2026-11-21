import { ArrowRight, ChevronDown } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { SIGN_UP } from "@/components/site/links";

/** Small mono label, as in "[ Security ]", with a live dot. */
export function Label({ children, dark = false }: { children: ReactNode; dark?: boolean }) {
  return (
    <p className={`inline-flex items-center gap-2 font-mono text-xs tracking-wider uppercase ${dark ? "text-ink-400" : "text-ink-500"}`}>
      <span className="relative flex size-1.5" aria-hidden>
        <span className="ping absolute inline-flex size-full rounded-full bg-emerald-400" />
        <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
      </span>
      [ {children} ]
    </p>
  );
}

/** Stagger delay for the n-th item of a group, for `.rise` and `[data-reveal]`. */
export function delay(i: number, step = 90): { style: Record<string, string> } {
  return { style: { "--d": `${i * step}ms` } };
}

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-6xl px-6 ${className}`}>{children}</div>;
}

/** Opening block of an inner page. Its parts rise in on load, one after another. */
export function PageHero({
  label,
  title,
  intro,
  actions,
  center = false,
  aside,
}: {
  label: string;
  title: string;
  intro: string;
  actions?: ReactNode;
  center?: boolean;
  aside?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden border-b border-ink-200/70">
      <div
        className="absolute inset-x-0 top-0 -z-10 h-[30rem] bg-[radial-gradient(50rem_24rem_at_50%_-20%,var(--color-brand-50),transparent)]"
        aria-hidden
      />
      <Container className={`pt-20 pb-16 md:pt-28 md:pb-20 ${center ? "text-center" : ""}`}>
        <div className={aside ? "grid items-center gap-12 lg:grid-cols-[1.1fr_1fr]" : ""}>
          <div className={center ? "mx-auto max-w-3xl" : "max-w-3xl"}>
            <div className="rise">
              <Label>{label}</Label>
            </div>
            <h1 className="rise mt-5 text-4xl font-semibold tracking-tight text-ink-950 md:text-6xl md:leading-[1.05]" {...delay(1, 110)}>
              {title}
            </h1>
            <p className={`rise mt-6 text-lg leading-8 text-ink-600 ${center ? "mx-auto max-w-2xl" : "max-w-2xl"}`} {...delay(2, 110)}>
              {intro}
            </p>
            {actions && (
              <div className={`rise mt-8 flex flex-wrap gap-3 ${center ? "justify-center" : ""}`} {...delay(3, 110)}>
                {actions}
              </div>
            )}
          </div>
          {aside && (
            <div className="rise" {...delay(3, 120)}>
              {aside}
            </div>
          )}
        </div>
      </Container>
    </section>
  );
}

export function Section({
  id,
  title,
  intro,
  dark = false,
  muted = false,
  children,
}: {
  id?: string;
  title: string;
  intro?: string;
  dark?: boolean;
  muted?: boolean;
  children: ReactNode;
}) {
  const tone = dark ? "bg-ink-950 text-white" : muted ? "bg-ink-50" : "";
  return (
    <section id={id} className={`scroll-mt-20 border-b border-ink-200/70 ${tone}`}>
      <Container className="py-20 md:py-24">
        <h2 data-reveal className={`max-w-3xl text-3xl font-semibold tracking-tight md:text-4xl ${dark ? "text-white" : "text-ink-950"}`}>
          {title}
        </h2>
        {intro && (
          <p data-reveal {...delay(1)} className={`mt-4 max-w-2xl text-base leading-7 ${dark ? "text-ink-300" : "text-ink-600"}`}>
            {intro}
          </p>
        )}
        <div className="mt-12">{children}</div>
      </Container>
    </section>
  );
}

export function ButtonLink({
  href,
  children,
  variant = "primary",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary" | "light";
}) {
  const style =
    variant === "primary"
      ? "bg-ink-950 text-white hover:bg-ink-800"
      : variant === "light"
        ? "bg-white text-ink-950 hover:bg-ink-100"
        : "border border-ink-300 bg-white text-ink-900 hover:border-ink-400 hover:bg-ink-50";
  const cls = `inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium transition-colors ${style}`;
  // Auth routes and mailto links need a full navigation, not a client-side transition.
  if (href.startsWith("/auth/") || href.startsWith("mailto:")) {
    return (
      <a href={href} className={cls}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}

/** Numbered tiles: "01 Upload", "02 Ask"… */
export function NumberedGrid({ items, dark = false }: { items: { title: string; body: string; href?: string }[]; dark?: boolean }) {
  return (
    <ol className={`grid border-t border-l sm:grid-cols-2 lg:grid-cols-4 ${dark ? "border-white/10" : "border-ink-200"}`}>
      {items.map((it, i) => {
        const inner = (
          <>
            <span className="absolute inset-x-0 top-0 h-0.5 origin-left scale-x-0 bg-brand-600 transition-transform duration-500 group-hover:scale-x-100" aria-hidden />
            <span className="font-mono text-xs text-ink-400">{String(i + 1).padStart(2, "0")}</span>
            <h3 className={`mt-6 text-lg font-semibold ${dark ? "text-white" : "text-ink-950"}`}>{it.title}</h3>
            <p className={`mt-2 text-sm leading-6 ${dark ? "text-ink-300" : "text-ink-600"}`}>{it.body}</p>
            {it.href && <ArrowRight className="mt-4 size-4 text-ink-400 transition-transform group-hover:translate-x-1" aria-hidden />}
          </>
        );
        const cell = `group relative block h-full overflow-hidden border-r border-b p-6 transition-colors ${dark ? "border-white/10 hover:bg-white/5" : "border-ink-200 hover:bg-white"}`;
        return (
          <li key={it.title} data-reveal {...delay(i)}>
            {it.href ? (
              <Link href={it.href} className={cell}>
                {inner}
              </Link>
            ) : (
              <div className={cell}>{inner}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** Title and one line, in a grid; the pattern used for "How it fits." and "Controls in place today." */
export function PointGrid({
  items,
  dark = false,
  columns = 3,
}: {
  items: { title: string; body: string; icon?: typeof ArrowRight }[];
  dark?: boolean;
  columns?: 2 | 3 | 4;
}) {
  const cols = columns === 4 ? "lg:grid-cols-4" : columns === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3";
  return (
    <div className={`grid gap-x-10 gap-y-10 sm:grid-cols-2 ${cols}`}>
      {items.map(({ title, body, icon: Icon }, i) => (
        <div key={title} data-reveal {...delay(i % 4)} className={`group relative border-t pt-5 ${dark ? "border-white/15" : "border-ink-200"}`}>
          <span className={`absolute -top-px left-0 h-px w-full origin-left scale-x-0 transition-transform duration-500 group-hover:scale-x-100 ${dark ? "bg-white" : "bg-ink-950"}`} aria-hidden />
          {Icon && (
            <Icon className={`mb-4 size-5 transition-transform duration-300 group-hover:-translate-y-0.5 ${dark ? "text-ink-300" : "text-ink-700"}`} aria-hidden />
          )}
          <h3 className={`font-semibold ${dark ? "text-white" : "text-ink-950"}`}>{title}</h3>
          <p className={`mt-2 text-sm leading-6 ${dark ? "text-ink-300" : "text-ink-600"}`}>{body}</p>
        </div>
      ))}
    </div>
  );
}

export function Questions({ items }: { items: { q: string; a: ReactNode }[] }) {
  return (
    <div className="divide-y divide-ink-200 border-y border-ink-200">
      {items.map(({ q, a }, i) => (
        <details key={q} data-reveal {...delay(i, 60)} className="group py-5">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-6 text-base font-medium text-ink-950 [&::-webkit-details-marker]:hidden">
            {q}
            <ChevronDown className="size-4 shrink-0 text-ink-400 transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <div className="slide-in mt-3 max-w-3xl text-sm leading-6 text-ink-600">{a}</div>
        </details>
      ))}
    </div>
  );
}

/** Two large tiles that close every page: talk to us, or start. */
export function Doors({ signedIn }: { signedIn: boolean }) {
  const tiles = [
    { href: "/contact", eyebrow: "See it on your documents", title: "Talk to us" },
    signedIn
      ? { href: "/home", eyebrow: "Welcome back", title: "Open your workspace" }
      : { href: SIGN_UP, eyebrow: "Set up in a few minutes", title: "Create your organization" },
  ];
  return (
    <section className="border-b border-ink-200/70">
      <div className="mx-auto grid max-w-6xl md:grid-cols-2">
        {tiles.map((t, i) => {
          const body = (
            <>
              <p className="text-sm text-ink-500 transition-colors group-hover:text-ink-400">{t.eyebrow}</p>
              <p className="mt-2 flex items-center gap-3 text-3xl font-semibold tracking-tight text-ink-950 transition-colors group-hover:text-white md:text-4xl">
                {t.title}
                <ArrowRight className="size-7 transition-transform group-hover:translate-x-1.5" aria-hidden />
              </p>
            </>
          );
          const cls = `group relative block overflow-hidden px-6 py-14 transition-colors duration-300 hover:bg-ink-950 md:py-20 ${i === 0 ? "md:border-r md:border-ink-200/70" : "border-t border-ink-200/70 md:border-t-0"}`;
          return t.href.startsWith("/auth/") ? (
            <a key={t.title} href={t.href} className={cls}>
              {body}
            </a>
          ) : (
            <Link key={t.title} href={t.href} className={cls}>
              {body}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
