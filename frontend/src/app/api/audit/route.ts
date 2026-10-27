/**
 * BFF Audit events endpoint.
 */

import { NextResponse } from "next/server";

export async function GET(): Promise<NextResponse> {
  const events = [
    {
      eventId: "evt-001",
      sequenceNumber: 1,
      eventType: "document_ingested",
      actorId: "auth0|admin-user-01",
      timestamp: "2026-10-27T10:00:00Z",
      payloadHash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      verified: true,
    },
    {
      eventId: "evt-002",
      sequenceNumber: 2,
      eventType: "query_executed",
      actorId: "auth0|member-user-02",
      timestamp: "2026-10-27T11:15:00Z",
      payloadHash: "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
      verified: true,
    },
  ];

  return NextResponse.json({ events });
}
