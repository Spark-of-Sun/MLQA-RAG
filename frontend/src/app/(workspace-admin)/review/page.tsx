"use client";

import { FileSearch, AlertCircle } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export default function ReviewQueuePage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Review & Quarantine Queue</h1>
        <p className="mt-1 text-sm text-slate-500">
          Manage emergency break-glass sessions, operator access approvals, and document quarantine.
        </p>
      </div>

      <Card title="OCR Quarantine Status (M1a Cut DR-15)">
        <div className="flex items-start gap-3 p-4 bg-amber-50/50 rounded-lg border border-amber-200">
          <AlertCircle className="h-5 w-5 text-amber-600 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-amber-900 leading-relaxed">
            <p className="font-semibold text-sm">OCR Review Screen Deferred in Profile `mvp-a`</p>
            <p className="mt-1">
              Per Scope Cut DR-15 and design specification, automatic OCR and quarantine review screens are disabled in release M1a.
              Scanned pages lacking a valid digital text layer fail-closed with status <code className="font-mono bg-amber-100 px-1 py-0.5 rounded">ocr_disabled</code> and are prevented from vector embedding.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
