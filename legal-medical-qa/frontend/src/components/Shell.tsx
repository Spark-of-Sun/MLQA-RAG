import Link from "next/link";
import type { ReactNode } from "react";
import { NAV, type Me } from "@/lib/capabilities";

/** The signed-in frame. Hidden menu items are convenience, not control (doc 17.1). */
export function Shell({ me, children }: { me: Me; children: ReactNode }) {
  const items = NAV.filter((item) => item.roles.includes(me.role));
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
          <span className="font-semibold">Onekami</span>
          <ul className="flex flex-1 gap-4 text-sm">
            {items.map((item) => (
              <li key={item.href}>
                <Link className="text-slate-700 hover:text-indigo-700" href={item.href}>
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
          <span className="text-xs uppercase tracking-wide text-slate-500">{me.role.replace("_", " ")}</span>
          <a className="text-sm text-slate-600 underline" href="/auth/logout">
            Sign out
          </a>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  const color = { info: "bg-indigo-50 text-indigo-900", warn: "bg-amber-50 text-amber-900", error: "bg-red-50 text-red-900" }[tone];
  return (
    <p role={tone === "error" ? "alert" : "status"} className={`rounded-md px-3 py-2 text-sm ${color}`}>
      {children}
    </p>
  );
}
