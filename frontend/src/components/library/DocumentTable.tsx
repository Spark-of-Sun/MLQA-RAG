"use client";

import { FileText, Clock, ShieldAlert } from "lucide-react";
import { Badge } from "../ui/Badge";

export interface DocumentItem {
  docId: string;
  title: string;
  filename: string;
  lifecycleState: string;
  confidentialityTier: string;
  chunksCount: number;
  createdAt: string;
}

interface DocumentTableProps {
  documents: DocumentItem[];
}

export function DocumentTable({ documents }: DocumentTableProps) {
  const getLifecycleBadge = (state: string) => {
    switch (state) {
      case "available":
        return <Badge variant="success">AVAILABLE</Badge>;
      case "indexing":
      case "chunking":
        return <Badge variant="info">PROCESSING</Badge>;
      case "rejected":
        return <Badge variant="error">REJECTED</Badge>;
      default:
        return <Badge variant="neutral">{state.toUpperCase()}</Badge>;
    }
  };

  const getTierBadge = (tier: string) => {
    switch (tier) {
      case "restricted":
        return <Badge variant="error">RESTRICTED</Badge>;
      case "confidential":
        return <Badge variant="warning">CONFIDENTIAL</Badge>;
      default:
        return <Badge variant="neutral">PUBLIC</Badge>;
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
        <thead className="bg-slate-50 text-xs font-semibold text-slate-500 uppercase">
          <tr>
            <th className="px-6 py-3">Document Title</th>
            <th className="px-6 py-3">Status</th>
            <th className="px-6 py-3">Confidentiality Tier</th>
            <th className="px-6 py-3">Chunks</th>
            <th className="px-6 py-3">Ingested At</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 bg-white">
          {documents.map((doc) => (
            <tr key={doc.docId} className="hover:bg-slate-50/50 transition-colors">
              <td className="px-6 py-4 font-medium text-slate-900 flex items-center gap-2">
                <FileText className="h-4 w-4 text-slate-400" />
                <div>
                  <p>{doc.title}</p>
                  <p className="text-xs text-slate-400 font-mono">{doc.filename}</p>
                </div>
              </td>
              <td className="px-6 py-4">{getLifecycleBadge(doc.lifecycleState)}</td>
              <td className="px-6 py-4">{getTierBadge(doc.confidentialityTier)}</td>
              <td className="px-6 py-4 font-mono text-xs text-slate-600">{doc.chunksCount} chunks</td>
              <td className="px-6 py-4 text-xs text-slate-500">{new Date(doc.createdAt).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
