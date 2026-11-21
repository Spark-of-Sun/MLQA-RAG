"use client";

import { BookOpen, CircleUserRound, FileText, History, LogOut, MessageSquareText, ShieldCheck, UserCog, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Logo } from "@/components/logo";
import { ThemeSwitch } from "@/components/theme-switch";
import { BRAND, ROLE_LABEL } from "@/lib/format";
import type { Me, Role } from "@/lib/types";

// Hidden menu items are convenience, not control: the gateway answers 404 for routes a role does not have.
const NAV: { href: string; label: string; icon: typeof FileText; roles: Role[] }[] = [
  { href: "/chat", label: "Ask", icon: MessageSquareText, roles: ["admin", "tenant"] },
  { href: "/library", label: "Library", icon: FileText, roles: ["admin", "tenant"] },
  { href: "/manage-tenants", label: "Manage members", icon: Users, roles: ["admin"] },
  { href: "/manage-admins", label: "Manage admins", icon: UserCog, roles: ["super_admin"] },
  { href: "/audit", label: "Audit trail", icon: History, roles: ["super_admin", "admin", "tenant"] },
  { href: "/profile", label: "Profile", icon: CircleUserRound, roles: ["super_admin", "admin", "tenant"] },
];

export function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  const pathname = usePathname();
  const m = me.membership;
  if (!m) return null;
  const items = NAV.filter((n) => n.roles.includes(m.role));
  const current = items.find((n) => pathname === n.href || pathname.startsWith(`${n.href}/`));
  const who = me.user.name || me.user.email || "Signed in";
  return (
    <div className="atmosphere flex h-full bg-ink-50">
      <aside className="flex w-60 shrink-0 flex-col border-r border-ink-200 bg-surface dark:bg-surface/80 dark:backdrop-blur-xl">
        <div className="border-b border-ink-100 px-4 py-4">
          {/* The product mark leads to the public home page, like the logo on any website. */}
          <Link href="/" className="inline-block rounded-md" title={`${BRAND} home page`}>
            <Logo />
          </Link>
          <div className="mt-3 rounded-lg bg-ink-50 px-3 py-2">
            <p className="truncate text-sm font-medium text-ink-900" title={m.organization.name}>
              {m.organization.name}
            </p>
            <p className="truncate text-xs text-ink-500">
              {m.workspace ? m.workspace.name : "Organization"} · {ROLE_LABEL[m.role]}
            </p>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 p-2" aria-label="Main">
          {items.map(({ href, label, icon: Icon }) => {
            const active = current?.href === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium ${
                  active ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-100 hover:text-ink-900"
                }`}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="mx-3 mb-3 flex items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-800">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Every answer sentence is checked against its source before you see it.
        </div>
        <div className="flex items-center gap-2 border-t border-ink-100 px-4 py-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-inverse text-xs font-semibold text-on-inverse">
            {who.slice(0, 1).toUpperCase()}
          </div>
          <Link href="/profile" className="min-w-0 flex-1 rounded-md hover:bg-ink-100" title="Your profile">
            <p className="truncate text-sm font-medium text-ink-800">{who}</p>
            {me.user.email && me.user.name && <p className="truncate text-xs text-ink-500">{me.user.email}</p>}
          </Link>
          {/* A full navigation, not a client-side Link: logout ends the server session and the Auth0 session. */}
          <a href="/auth/logout" className="rounded-md p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700" title="Sign out">
            <LogOut className="size-4" aria-label="Sign out" />
          </a>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-ink-200 bg-surface px-6 dark:bg-surface/70 dark:backdrop-blur-xl">
          <p className="truncate text-sm text-ink-500">
            <span className="text-ink-700">{m.workspace ? m.workspace.name : m.organization.name}</span>
            {current && <span className="text-ink-400"> / </span>}
            {current && <span className="font-medium text-ink-900">{current.label}</span>}
          </p>
          <div className="flex items-center gap-4">
            <Link href="/docs" className="flex items-center gap-1.5 text-sm text-ink-600 hover:text-ink-950">
              <BookOpen className="size-4" aria-hidden /> Docs
            </Link>
            <ThemeSwitch />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
