import { AuditTable } from "@/components/audit/AuditTable";

export default function AuditPage() {
  const initialEvents = [
    {
      eventId: "evt-0001",
      sequenceNumber: 1,
      eventType: "document_ingested",
      actorId: "auth0|superadmin-01",
      timestamp: "2026-10-25T12:00:00Z",
      payloadHash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      verified: true,
    },
    {
      eventId: "evt-0002",
      sequenceNumber: 2,
      eventType: "workspace_created",
      actorId: "auth0|superadmin-01",
      timestamp: "2026-10-25T12:05:00Z",
      payloadHash: "b5a2c96250612366ea8c2c10df6be086022720f89200541a1a011d6d2e777e45",
      verified: true,
    },
    {
      eventId: "evt-0003",
      sequenceNumber: 3,
      eventType: "tenant_admitted",
      actorId: "auth0|admin-02",
      timestamp: "2026-10-26T09:30:00Z",
      payloadHash: "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
      verified: true,
    },
    {
      eventId: "evt-0004",
      sequenceNumber: 4,
      eventType: "query_executed",
      actorId: "auth0|legal-rev-03",
      timestamp: "2026-10-27T11:15:00Z",
      payloadHash: "fa4623ca2b06e163ba0f97f538724485e43a5fb17cd3712f1219fc7d814c83d5",
      verified: true,
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Cryptographic Audit Ledger</h1>
        <p className="mt-1 text-sm text-slate-500">
          Append-only, SHA-256 hash-chained event timeline tracking document access, ingestion, and membership transitions.
        </p>
      </div>

      <AuditTable events={initialEvents} />
    </div>
  );
}
