import { DocumentTable } from "@/components/library/DocumentTable";
import { UploadDropzone } from "@/components/library/UploadDropzone";

export default function LibraryPage() {
  const initialDocs = [
    {
      docId: "00000000-0000-0000-0000-000000000101",
      title: "Credit Agreement 2024 (Alpha Corp)",
      filename: "credit_agreement_2024.pdf",
      lifecycleState: "available",
      confidentialityTier: "confidential",
      chunksCount: 14,
      createdAt: "2026-10-25T12:00:00Z",
    },
    {
      docId: "00000000-0000-0000-0000-000000000102",
      title: "Master Services Agreement (Acme Partners)",
      filename: "msa_alpha_v2.pdf",
      lifecycleState: "available",
      confidentialityTier: "restricted",
      chunksCount: 22,
      createdAt: "2026-10-26T09:30:00Z",
    },
    {
      docId: "00000000-0000-0000-0000-000000000103",
      title: "Non-Disclosure Agreement (Beta Tech)",
      filename: "nda_executed_final.pdf",
      lifecycleState: "available",
      confidentialityTier: "public",
      chunksCount: 8,
      createdAt: "2026-10-27T08:15:00Z",
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Document Library</h1>
        <p className="mt-1 text-sm text-slate-500">
          Manage workspace legal agreements, confidentiality tiers, and view chunk extraction status.
        </p>
      </div>

      <UploadDropzone />

      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-slate-900">Authorized Workspace Documents</h2>
        <DocumentTable documents={initialDocs} />
      </div>
    </div>
  );
}
