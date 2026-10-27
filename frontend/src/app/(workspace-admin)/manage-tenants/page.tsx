"use client";

import { Users, UserPlus, CheckCircle, Shield } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export default function ManageTenantsPage() {
  const tenants = [
    {
      id: "ten-001",
      email: "attorney1@alpha.law",
      role: "legal_reviewer",
      status: "active",
      joinedAt: "2026-10-20",
      mattersCount: 5,
    },
    {
      id: "ten-002",
      email: "paralegal.clara@alpha.law",
      role: "member",
      status: "active",
      joinedAt: "2026-10-22",
      mattersCount: 3,
    },
    {
      id: "ten-003",
      email: "external.counsel@partner.com",
      role: "legal_reviewer",
      status: "pending_approval",
      joinedAt: "Just now",
      mattersCount: 0,
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Workspace Tenant Management</h1>
          <p className="mt-1 text-sm text-slate-500">
            Administer workspace members, review pending membership admissions, and configure join codes.
          </p>
        </div>
        <Button size="sm">
          <UserPlus className="h-4 w-4 mr-1.5" />
          <span>Generate Join Code</span>
        </Button>
      </div>

      {/* Admin Code Join Policy */}
      <Card title="Active Workspace Join Policy" description="Configure admission gate requirements for new members joining this workspace.">
        <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-200">
          <div>
            <p className="text-sm font-semibold text-slate-800">Policy: Explicit Admin Approval Required</p>
            <p className="text-xs text-slate-500 mt-1">Code: WS-JOIN-9941-KLP | 25 uses remaining</p>
          </div>
          <Badge variant="warning">APPROVAL GATE ON</Badge>
        </div>
      </Card>

      {/* Tenants Table */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold text-slate-500 uppercase">
            <tr>
              <th className="px-6 py-3">Member Email</th>
              <th className="px-6 py-3">Role</th>
              <th className="px-6 py-3">Status</th>
              <th className="px-6 py-3">Matters Assigned</th>
              <th className="px-6 py-3">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {tenants.map((ten) => (
              <tr key={ten.id} className="hover:bg-slate-50/50">
                <td className="px-6 py-4 font-medium text-slate-900">{ten.email}</td>
                <td className="px-6 py-4">
                  <Badge variant="neutral">{ten.role.replace("_", " ").toUpperCase()}</Badge>
                </td>
                <td className="px-6 py-4">
                  {ten.status === "active" ? (
                    <Badge variant="success">ACTIVE</Badge>
                  ) : (
                    <Badge variant="warning">PENDING APPROVAL</Badge>
                  )}
                </td>
                <td className="px-6 py-4 text-xs font-mono text-slate-600">{ten.mattersCount} matters</td>
                <td className="px-6 py-4">
                  {ten.status === "pending_approval" ? (
                    <Button size="sm">Approve Member</Button>
                  ) : (
                    <Button variant="outline" size="sm">Edit Grants</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
