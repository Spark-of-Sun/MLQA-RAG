"use client";

import { useState } from "react";
import { api, ApiError, uploadDocument } from "@/lib/api-client";
import { useResource } from "@/lib/use-resource";
import { Notice } from "@/components/Shell";

interface Doc {
  id: string;
  title: string;
  status: string;
  visibility: "private" | "matter";
  tier: number;
  matter_id: string | null;
  failure_reason: string | null;
  created_at: string;
}
interface Matter {
  id: string;
  label: string;
}

const STATUS_TEXT: Record<string, string> = {
  uploading: "Uploading", scanning: "Scanning", parsing: "Reading", ocr_review: "Needs page review", indexing: "Indexing",
  indexed: "Ready", failed: "Failed", held: "On hold", deleting: "Deleting",
};
const REASONS: Record<string, string> = {
  malware_eicar: "Rejected: the file contains malware.", pdf_active_content: "Rejected: the PDF contains active content.",
  checksum_mismatch: "The upload was corrupted. Please try again.", unsupported_format: "This file type is not supported.",
  parser_error: "The file could not be read.", no_text: "No readable text was found.", size_limit: "The file is too large.",
};

export function Library() {
  const [visibility, setVisibility] = useState<"private" | "matter">("private");
  const [matter, setMatter] = useState("");
  const [tier, setTier] = useState(1);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Polls so the status of scanning and indexing keeps moving.
  const [data, refresh] = useResource(async () => {
    const [d, m] = await Promise.all([api<{ documents: Doc[] }>("/documents"), api<{ matters: Matter[] }>("/workspace/matters").catch(() => ({ matters: [] }))]);
    return { docs: d.documents, matters: m.matters };
  }, 4000);
  const docs = data?.docs ?? [];
  const matters = data?.matters ?? [];

  async function onFile(file: File | undefined) {
    if (!file) return;
    if (visibility === "matter" && !matter) return setMessage("Choose a matter to share this document with.");
    setBusy(true);
    setMessage(null);
    try {
      await uploadDocument(file, { visibility, matter_id: visibility === "matter" ? matter : undefined, tier });
      refresh();
    } catch (e) {
      setMessage(e instanceof ApiError ? `Upload failed (${e.title}).` : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="up" className="space-y-3 rounded-lg bg-white p-4 shadow-sm">
        <h2 id="up" className="font-medium">Add a document</h2>
        <div className="flex flex-wrap items-end gap-4 text-sm">
          <label>Who can read it
            <select value={visibility} onChange={(e) => setVisibility(e.target.value as "private" | "matter")} className="mt-1 block rounded border border-slate-300 px-2 py-1">
              <option value="private">Only me</option>
              <option value="matter">People with access to a matter</option>
            </select>
          </label>
          {visibility === "matter" && (
            <label>Matter
              <select value={matter} onChange={(e) => setMatter(e.target.value)} className="mt-1 block rounded border border-slate-300 px-2 py-1">
                <option value="">Choose…</option>
                {matters.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
          )}
          <label>Confidentiality
            <select value={tier} onChange={(e) => setTier(Number(e.target.value))} className="mt-1 block rounded border border-slate-300 px-2 py-1">
              <option value={1}>1 Internal</option><option value={2}>2 Confidential</option>
              <option value={3}>3 Privileged / PHI</option><option value={4}>4 Restricted</option>
            </select>
          </label>
          <label className="rounded bg-indigo-700 px-4 py-2 text-white">
            {busy ? "Uploading…" : "Choose a file"}
            <input type="file" className="sr-only" disabled={busy} accept=".pdf,.docx,.html,.htm,.xml,.txt" onChange={(e) => void onFile(e.target.files?.[0])} />
          </label>
        </div>
        {message && <Notice tone="error">{message}</Notice>}
      </section>

      <section aria-labelledby="docs" className="rounded-lg bg-white p-4 shadow-sm">
        <h2 id="docs" className="mb-3 font-medium">Your documents</h2>
        {docs.length === 0 ? <p className="text-sm text-slate-500">Nothing here yet.</p> : (
          <table className="w-full text-left text-sm">
            <thead className="text-slate-500"><tr><th scope="col" className="py-1">Title</th><th scope="col">Status</th><th scope="col">Access</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="py-2">{d.title}</td>
                  <td>
                    {STATUS_TEXT[d.status] ?? d.status}
                    {d.failure_reason && <span className="block text-xs text-red-700">{REASONS[d.failure_reason] ?? d.failure_reason}</span>}
                    {d.status === "ocr_review" && <span className="block text-xs text-amber-700">A page has no text layer and must be reviewed before it can be searched.</span>}
                  </td>
                  <td>{d.visibility === "private" ? "Only you" : "Shared to a matter"}, tier {d.tier}</td>
                  <td className="text-right">
                    <button type="button" className="text-red-700 underline" onClick={() => { if (window.confirm(`Delete "${d.title}"? Its content is erased for good.`)) void api(`/documents/${d.id}`, { method: "DELETE" }).then(() => refresh()).catch(() => setMessage("This document cannot be deleted (legal hold or retention).")); }}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
