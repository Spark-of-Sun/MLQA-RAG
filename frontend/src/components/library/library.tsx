"use client";

import { AlertTriangle, FileText, Lock, Trash2, UploadCloud, Users } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert, Badge, Card, ConfirmButton, EmptyState, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatBytes, timeAgo } from "@/lib/format";
import type { DocumentRow } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.html,.htm,.xml,.txt,.md";

export function Library({ isAdmin }: { isAdmin: boolean }) {
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [visibility, setVisibility] = useState<"workspace" | "private">(isAdmin ? "workspace" : "private");
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await api.get<DocumentRow[]>("documents"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const processing = docs?.some((d) => d.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => void load(), 2500);
    return () => clearInterval(t);
  }, [processing, load]);

  async function upload(files: FileList | File[]) {
    setError(null);
    setNotice(null);
    const list = Array.from(files);
    let ok = 0;
    for (const file of list) {
      setUploading(file.name);
      const form = new FormData();
      form.append("file", file);
      form.append("visibility", visibility);
      try {
        await api.upload("documents", form);
        ok += 1;
      } catch (e) {
        setError(`${file.name}: ${errorMessage(e)}`);
      }
    }
    setUploading(null);
    if (ok) setNotice(`${ok} file${ok === 1 ? "" : "s"} uploaded. Indexing runs in the background.`);
    if (input.current) input.current.value = "";
    await load();
  }

  async function remove(doc: DocumentRow) {
    try {
      await api.del(`documents/${doc.id}`);
      setNotice(`Deleted “${doc.title}”.`);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <PageHeader
        title="Library"
        subtitle={
          isAdmin
            ? "Shared documents are visible to everyone in your workspace. Private documents are visible only to you."
            : "Documents you upload are private to you. Documents shared by your workspace admin appear here too."
        }
      />

      <Card className="mb-6 p-5">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (e.dataTransfer.files.length) void upload(e.dataTransfer.files);
          }}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
            dragging ? "border-brand-400 bg-brand-50" : "border-ink-200 bg-ink-50/50"
          }`}
        >
          <UploadCloud className="size-7 text-ink-400" aria-hidden />
          <p className="mt-2 text-sm font-medium text-ink-800">Drop files here, or</p>
          <label className="mt-2 cursor-pointer rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
            Choose files
            <input
              ref={input}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              disabled={uploading !== null}
              onChange={(e) => e.target.files && void upload(e.target.files)}
            />
          </label>
          <p className="mt-2 text-xs text-ink-500">PDF (with a text layer), DOCX, HTML, XML (JATS, SPL drug labels, eCFR), TXT · up to 25 MB</p>
          {isAdmin && (
            <div className="mt-4 inline-flex rounded-lg border border-ink-200 bg-white p-0.5 text-xs" role="radiogroup" aria-label="Visibility">
              {(["workspace", "private"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={visibility === v}
                  onClick={() => setVisibility(v)}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium ${
                    visibility === v ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-ink-50"
                  }`}
                >
                  {v === "workspace" ? <Users className="size-3.5" aria-hidden /> : <Lock className="size-3.5" aria-hidden />}
                  {v === "workspace" ? "Share with workspace" : "Private to me"}
                </button>
              ))}
            </div>
          )}
          {uploading && (
            <div className="mt-4">
              <Spinner label={`Uploading ${uploading}…`} />
            </div>
          )}
        </div>
        <div className="mt-3 space-y-2">
          {error && <Alert>{error}</Alert>}
          {notice && <Alert tone="green">{notice}</Alert>}
        </div>
      </Card>

      <Card>
        {docs === null ? (
          <div className="p-6">
            <Spinner label="Loading documents…" />
          </div>
        ) : docs.length === 0 ? (
          <EmptyState icon={<FileText className="size-5" />} title="No documents yet">
            Upload a contract, case file, drug label or clinical document to start asking questions.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-ink-100 text-xs text-ink-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Document</th>
                  <th className="px-3 py-3 font-medium">Access</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium">Indexed</th>
                  <th className="px-3 py-3 font-medium">Owner</th>
                  <th className="px-3 py-3 font-medium">Added</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {docs.map((d) => (
                  <tr key={d.id} className="align-top">
                    <td className="max-w-sm px-5 py-3">
                      <p className="font-medium text-ink-900">{d.title}</p>
                      <p className="truncate text-xs text-ink-500">
                        {d.filename} · {d.file_type.toUpperCase()} · {formatBytes(d.size_bytes)}
                      </p>
                      {d.status === "failed" && d.error && <p className="mt-1 text-xs text-rose-700">{d.error}</p>}
                      {d.notes && (
                        <p className="mt-1 flex items-start gap-1 text-xs text-amber-800">
                          <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden />
                          {d.notes}
                        </p>
                      )}
                      {d.structure === "fallback" && (
                        <p className="mt-1 text-xs text-ink-500">No headings detected: split into paragraphs.</p>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {d.visibility === "workspace" ? (
                        <Badge tone="blue">
                          <Users className="size-3" aria-hidden /> Shared
                        </Badge>
                      ) : (
                        <Badge>
                          <Lock className="size-3" aria-hidden /> Private
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="px-3 py-3 text-xs text-ink-600">
                      {d.status === "ready" ? (
                        <>
                          {d.chunk_count} passages
                          {d.page_count ? ` · ${d.page_count} pages` : ""}
                        </>
                      ) : d.status === "processing" ? (
                        <Spinner />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-3 py-3 text-xs text-ink-600">{d.mine ? "You" : d.owner}</td>
                    <td className="px-3 py-3 text-xs whitespace-nowrap text-ink-500">{timeAgo(d.created_at)}</td>
                    <td className="px-5 py-3 text-right">
                      {(d.mine || (isAdmin && d.visibility === "workspace")) && (
                        <ConfirmButton label="Delete" variant="ghost" onConfirm={() => remove(d)} confirmLabel="Delete?" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-400">
        <Trash2 className="size-3" aria-hidden /> Deleting a document removes its passages from search at once. Past answers
        that cited it show the source as unavailable.
      </p>
    </div>
  );
}
