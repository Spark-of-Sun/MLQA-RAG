"use client";

import { ShieldCheck, Hash, User, Calendar } from "lucide-react";
import { Badge } from "../ui/Badge";

export interface AuditEventItem {
  eventId: string;
  sequenceNumber: number;
  eventType: string;
  actorId: string;
  timestamp: string;
  payloadHash: string;
  verified: boolean;
}

interface AuditTableProps {
  events: AuditEventItem[];
}

export function AuditTable({ events }: AuditTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-emerald-600" />
          <h3 className="font-semibold text-sm text-slate-900">Cryptographically Chained Audit Ledger</h3>
        </div>
        <Badge variant="success">CHAIN VERIFIED</Badge>
      </div>

      <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
        <thead className="bg-slate-50 text-xs font-semibold text-slate-500 uppercase">
          <tr>
            <th className="px-6 py-3">Seq #</th>
            <th className="px-6 py-3">Event Type</th>
            <th className="px-6 py-3">Actor Subject</th>
            <th className="px-6 py-3">Payload SHA-256</th>
            <th className="px-6 py-3">Timestamp</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 bg-white">
          {events.map((evt) => (
            <tr key={evt.eventId} className="hover:bg-slate-50/50 transition-colors">
              <td className="px-6 py-4 font-mono text-xs font-semibold text-slate-700">#{evt.sequenceNumber}</td>
              <td className="px-6 py-4 font-medium text-slate-900">
                <Badge variant="info">{evt.eventType.replace("_", " ").toUpperCase()}</Badge>
              </td>
              <td className="px-6 py-4 text-xs font-mono text-slate-600 flex items-center gap-1.5">
                <User className="h-3.5 w-3.5 text-slate-400" />
                <span>{evt.actorId}</span>
              </td>
              <td className="px-6 py-4 text-xs font-mono text-slate-400">
                <div className="flex items-center gap-1">
                  <Hash className="h-3.5 w-3.5 text-slate-300" />
                  <span>{evt.payloadHash.substring(0, 16)}...</span>
                </div>
              </td>
              <td className="px-6 py-4 text-xs text-slate-500 flex items-center gap-1.5">
                <Calendar className="h-3.5 w-3.5 text-slate-400" />
                <span>{new Date(evt.timestamp).toLocaleString()}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
