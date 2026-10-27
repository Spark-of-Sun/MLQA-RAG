"use client";

import { ShieldCheck, Check, X, Clock } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export default function GovernancePage() {
  const requests = [
    {
      id: "gov-001",
      type: "wall_lift_request",
      requestedBy: "Elena Rostova (Workspace Admin)",
      reason: "Emergency matter crossover discovery for Matter #2024-C9",
      timestamp: "1 hour ago",
      status: "pending_super_admin",
    },
    {
      id: "gov-002",
      type: "private_read_enable",
      requestedBy: "Marcus Vance (Workspace Admin)",
      reason: "Auditor compliance sampling for Q3 regulatory filings",
      timestamp: "3 hours ago",
      status: "pending_super_admin",
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Governance & Approval Center</h1>
        <p className="mt-1 text-sm text-slate-500">
          Super Admin review queue for ethical wall lift requests, private document reading elevation, and security exceptions.
        </p>
      </div>

      <div className="space-y-4">
        {requests.map((req) => (
          <Card key={req.id}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant="warning">{req.type.replace(/_/g, " ").toUpperCase()}</Badge>
                  <span className="text-xs text-slate-400 font-mono">ID: {req.id}</span>
                </div>
                <h3 className="font-semibold text-slate-900 text-sm mt-2">{req.reason}</h3>
                <p className="text-xs text-slate-500 mt-1">Requested by: {req.requestedBy} • {req.timestamp}</p>
              </div>

              <div className="flex items-center gap-2">
                <Button variant="danger" size="sm">
                  <X className="h-4 w-4 mr-1" />
                  <span>Reject</span>
                </Button>
                <Button size="sm">
                  <Check className="h-4 w-4 mr-1" />
                  <span>Approve Request</span>
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
