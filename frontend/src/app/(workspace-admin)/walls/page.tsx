"use client";

import { ShieldCheck, Lock, Unlock, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export default function EthicalWallsPage() {
  const walls = [
    {
      id: "wall-01",
      matterName: "Project Titan Acquisition (Matter #2024-C9)",
      restrictedGroup: "Corporate M&A Advisory Team",
      isolatedGroup: "Regulatory Antitrust Defense Team",
      status: "active_enforced",
      createdAt: "2026-10-15",
    },
    {
      id: "wall-02",
      matterName: "Biomedical Patent Dispute (Matter #2024-L12)",
      restrictedGroup: "Patent Litigation Team",
      isolatedGroup: "Licensing Counsel",
      status: "active_enforced",
      createdAt: "2026-10-18",
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Ethical Walls & Isolation Boundaries</h1>
          <p className="mt-1 text-sm text-slate-500">
            Enforce client matter isolation, manage conflict of interest walls, and request wall-lift elevations.
          </p>
        </div>
        <Button size="sm">
          <Lock className="h-4 w-4 mr-1.5" />
          <span>Establish Ethical Wall</span>
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {walls.map((wall) => (
          <Card key={wall.id}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant="success">ISOLATION ACTIVE</Badge>
                  <span className="text-xs font-mono text-slate-400">ID: {wall.id}</span>
                </div>
                <h3 className="font-semibold text-slate-900 text-base mt-2">{wall.matterName}</h3>
                <div className="mt-2 text-xs text-slate-600 space-y-1">
                  <p><span className="font-medium text-slate-700">Enforced Boundary:</span> {wall.restrictedGroup} ⟷ {wall.isolatedGroup}</p>
                  <p><span className="font-medium text-slate-700">Established:</span> {wall.createdAt}</p>
                </div>
              </div>

              <Button variant="outline" size="sm">
                <Unlock className="h-4 w-4 mr-1.5 text-amber-600" />
                <span>Request Wall Lift</span>
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
