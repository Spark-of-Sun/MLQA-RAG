"use client";

import * as React from "react";
import { Users, KeyRound, ShieldAlert, RotateCw, Plus } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export default function ManageAdminsPage() {
  const admins = [
    {
      id: "adm-001",
      name: "Marcus Vance",
      email: "m.vance@alpha.internal",
      state: "active",
      tenantCount: 18,
      documentCount: 42,
      tokenUsage30d: "1.42M tokens",
      lastActive: "10 mins ago",
    },
    {
      id: "adm-002",
      name: "Elena Rostova",
      email: "e.rostova@beta.internal",
      state: "active",
      tenantCount: 12,
      documentCount: 29,
      tokenUsage30d: "840K tokens",
      lastActive: "2 hours ago",
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Organization Administrators</h1>
          <p className="mt-1 text-sm text-slate-500">
            Super Admin center: manage workspace administrators, rotate organization codes, and audit usage.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <RotateCw className="h-4 w-4 mr-1.5" />
            <span>Rotate Org Code</span>
          </Button>
          <Button size="sm">
            <Plus className="h-4 w-4 mr-1.5" />
            <span>Invite Administrator</span>
          </Button>
        </div>
      </div>

      {/* Organization Code Panel */}
      <Card title="Active Organization Enrollment Code" description="Cryptographic single-use enrollment secrets are shown once and cleared from state.">
        <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-200">
          <div>
            <p className="font-mono text-sm font-semibold text-slate-800">ORG-SEC-8921-XKQ7</p>
            <p className="text-xs text-slate-500 mt-1">Lookup ID: org_key_alpha | 10 uses remaining | Valid until 2026-11-15</p>
          </div>
          <Badge variant="success">ACTIVE</Badge>
        </div>
      </Card>

      {/* Administrators Table */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold text-slate-500 uppercase">
            <tr>
              <th className="px-6 py-3">Administrator</th>
              <th className="px-6 py-3">State</th>
              <th className="px-6 py-3">Workspaces</th>
              <th className="px-6 py-3">Documents</th>
              <th className="px-6 py-3">30-Day Tokens</th>
              <th className="px-6 py-3">Last Active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {admins.map((adm) => (
              <tr key={adm.id} className="hover:bg-slate-50/50">
                <td className="px-6 py-4 font-medium text-slate-900">
                  <div>
                    <p>{adm.name}</p>
                    <p className="text-xs text-slate-400">{adm.email}</p>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <Badge variant="success">ACTIVE</Badge>
                </td>
                <td className="px-6 py-4 font-mono text-xs text-slate-600">{adm.tenantCount} tenants</td>
                <td className="px-6 py-4 font-mono text-xs text-slate-600">{adm.documentCount} docs</td>
                <td className="px-6 py-4 text-xs font-medium text-slate-800">{adm.tokenUsage30d}</td>
                <td className="px-6 py-4 text-xs text-slate-500">{adm.lastActive}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
