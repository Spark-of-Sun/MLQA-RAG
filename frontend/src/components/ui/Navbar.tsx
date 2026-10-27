"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, BookOpen, ShieldCheck, Settings, Users, FileCheck } from "lucide-react";
import { Badge } from "./Badge";

interface NavbarProps {
  role?: string;
  userEmail?: string;
}

export function Navbar({ role = "legal_reviewer", userEmail = "attorney@example.law" }: NavbarProps) {
  const pathname = usePathname();

  const navLinks = [
    { href: "/chat", label: "Q&A Chat", icon: MessageSquare, roles: ["admin", "legal_reviewer", "medical_reviewer", "member", "auditor"] },
    { href: "/library", label: "Document Library", icon: BookOpen, roles: ["admin", "legal_reviewer", "medical_reviewer", "member"] },
    { href: "/audit", label: "Audit Ledger", icon: ShieldCheck, roles: ["super_admin", "admin", "auditor"] },
    { href: "/manage-admins", label: "Manage Admins", icon: Users, roles: ["super_admin"] },
    { href: "/manage-tenants", label: "Workspace Tenants", icon: FileCheck, roles: ["admin"] },
    { href: "/account", label: "Account", icon: Settings, roles: ["super_admin", "admin", "legal_reviewer", "medical_reviewer", "member", "auditor"] },
  ];

  const visibleLinks = navLinks.filter((link) => link.roles.includes(role));

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-6">
          <Link href="/chat" className="flex items-center gap-2 font-bold text-slate-900 text-lg">
            <span className="rounded bg-slate-900 p-1.5 text-white">ML</span>
            <span>MLQA-RAG</span>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {visibleLinks.map((item) => {
              const Icon = item.icon;
              const isActive = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-slate-100 text-slate-900"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <Badge variant="info">{role.replace("_", " ").toUpperCase()}</Badge>
          <span className="text-xs text-slate-500 hidden sm:inline-block">{userEmail}</span>
        </div>
      </div>
    </header>
  );
}
