/**
 * BFF Document management endpoint.
 */

import { NextResponse, type NextRequest } from "next/server";

export async function GET(): Promise<NextResponse> {
  const documents = [
    {
      docId: "00000000-0000-0000-0000-000000000101",
      title: "Credit Agreement 2024",
      filename: "credit_agreement_2024.pdf",
      lifecycleState: "available",
      confidentialityTier: "confidential",
      chunksCount: 14,
      createdAt: "2026-10-25T12:00:00Z",
    },
    {
      docId: "00000000-0000-0000-0000-000000000102",
      title: "Master Services Agreement",
      filename: "msa_alpha_v2.pdf",
      lifecycleState: "available",
      confidentialityTier: "restricted",
      chunksCount: 22,
      createdAt: "2026-10-26T09:30:00Z",
    },
  ];

  return NextResponse.json({ documents });
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const formData = await req.formData();
  const file = formData.get("file");

  if (!file) {
    return NextResponse.json({ error: "File is required" }, { status: 400 });
  }

  return NextResponse.json({
    status: "uploaded",
    docId: crypto.randomUUID(),
    message: "File queued for scanning and ingestion pipeline",
  });
}
