"use client";

import * as React from "react";
import { KeyRound, Shield, Users, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

export default function OnboardingPage() {
  const [selectedRole, setSelectedRole] = React.useState<string>("legal_reviewer");
  const [inviteCode, setInviteCode] = React.useState("");
  const [status, setStatus] = React.useState<"select" | "pending">("select");

  const roles = [
    {
      id: "legal_reviewer",
      title: "Legal Reviewer",
      desc: "Review legal agreements, contracts, and execute verified semantic Q&A queries.",
      icon: Shield,
    },
    {
      id: "member",
      title: "Workspace Member",
      desc: "Standard workspace participant with read permissions on authorized matters.",
      icon: Users,
    },
    {
      id: "admin",
      title: "Workspace Administrator",
      desc: "Manage workspace tenants, ethical walls, join policies, and document visibility.",
      icon: KeyRound,
    },
  ];

  const handleJoin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteCode.trim()) {
      return;
    }
    setStatus("pending");
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <div className="text-center mb-10">
        <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Organization Onboarding</h1>
        <p className="mt-2 text-sm text-slate-600">
          Enter your single-use onboarding authorization code or request membership in a workspace.
        </p>
      </div>

      {status === "select" ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {roles.map((r) => {
              const Icon = r.icon;
              const isSelected = selectedRole === r.id;
              return (
                <div
                  key={r.id}
                  onClick={() => setSelectedRole(r.id)}
                  className={`cursor-pointer rounded-lg border p-5 transition-all ${
                    isSelected
                      ? "border-slate-900 bg-white ring-2 ring-slate-900 shadow-sm"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <Icon className={`h-6 w-6 mb-3 ${isSelected ? "text-slate-900" : "text-slate-400"}`} />
                  <h3 className="font-semibold text-slate-900 text-sm">{r.title}</h3>
                  <p className="text-xs text-slate-500 mt-1 leading-relaxed">{r.desc}</p>
                </div>
              );
            })}
          </div>

          <Card title="Authorization Code Entry">
            <form onSubmit={handleJoin} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                  Organization / Workspace Join Code
                </label>
                <input
                  type="text"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  placeholder="e.g. ORG-SEC-8921-XKQ7"
                  className="mt-1 block w-full rounded-md border border-slate-300 px-4 py-2.5 text-sm font-mono focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
                  required
                />
              </div>

              <Button type="submit" className="w-full">
                <span>Submit Authorization Code</span>
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Button>
            </form>
          </Card>
        </div>
      ) : (
        <Card className="text-center py-10">
          <div className="mx-auto h-12 w-12 rounded-full bg-amber-50 flex items-center justify-center border border-amber-200 mb-4">
            <KeyRound className="h-6 w-6 text-amber-600" />
          </div>
          <h2 className="text-xl font-bold text-slate-900">Membership Pending Administrator Approval</h2>
          <p className="mt-2 text-sm text-slate-600 max-w-md mx-auto">
            Your onboarding code has been submitted to workspace administrators for cryptographic key enrollment and role authorization.
          </p>
          <div className="mt-6">
            <Button variant="outline" onClick={() => setStatus("select")}>
              Return to Code Entry
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
