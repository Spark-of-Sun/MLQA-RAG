"use client";

import { AlertTriangle, FileText, Lock, Share2, Trash2, UploadCloud, UserCheck, Users } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert, Badge, Card, ConfirmButton, EmptyState, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatBytes, timeAgo } from "@/lib/format";
import type { DocumentRow, MemberRow } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.html,.htm,.xml,.txt,.md";

type Audience = "workspace" | "members" | "private";

const AUDIENCES: { value: Audience; label: string; icon: typeof Users }[] = [
  { value: "workspace", label: "Whole workspace", icon: Users },
  { value: "members", label: "Selected members", icon: UserCheck },
  { value: "private", label: "Only me", icon: Lock },
];

function names(list: { name: string }[]): string {
  const all = list.map((x) => x.name);
  if (all.length <= 2) return all.join(" and ");
  return `${all.slice(0, 2).join(", ")} and ${all.length - 2} more`;
}

/** Who shared the document, and with whom, from the viewer's point of view. */
function Access({ d }: { d: DocumentRow }) {
  if (d.access === "private") {
    return (
      <Badge>
        <Lock className="size-3" aria-hidden /> Private
      </Badge>
    );
  }
  const by = d.shared_by === "you" ? "Shared by you" : d.shared_by === "admin" ? "Shared by admin" : "Shared by member";
  const tone = d.shared_by === "you" ? "green" : d.shared_by === "admin" ? "blue" : "gray";
  let detail: string;
  if (d.access === "workspace") detail = "with the whole workspace";
  else if (!d.mine) detail = d.shared_by === "member" ? `${d.owner}, with you` : "with you";
  else if (d.shared_with.every((x) => x.role === "admin")) detail = `with your admin (${names(d.shared_with)})`;
  else detail = `with ${names(d.shared_with)}`;
  return (
    <div className="space-y-0.5" title={d.access === "shared" && d.mine ? d.shared_with.map((x) => x.name).join(", ") : undefined}>
      <Badge tone={tone}>
        <Share2 className="size-3" aria-hidden /> {by}
      </Badge>
      <p className="max-w-48 text-[11px] leading-tight text-ink-500">{detail}</p>
    </div>
  );
}

/**
 * `workspaceVisibility` and `namedShares` are frozen MVP-only features (DEV-14, DEV-21): while a flag is off its
 * upload option is hidden (the API refuses it too) and uploads are private to their owner.
 */
export function Library({
  isAdmin,
  workspaceVisibility,
  namedShares,
}: {
  isAdmin: boolean;
  workspaceVisibility: boolean;
  namedShares: boolean;
}) {
  const audiences = AUDIENCES.filter(
    (a) => a.value === "private" || (a.value === "workspace" ? workspaceVisibility : namedShares),
  );
  const chooseAudience = isAdmin && audiences.length > 1;
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [audience, setAudience] = useState<Audience>(isAdmin && workspaceVisibility ? "workspace" : "private");
  const [shareWithAdmin, setShareWithAdmin] = useState(false);
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
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

  useEffect(() => {
    if (!isAdmin || !namedShares) return;
    api
      .get<MemberRow[]>("workspace/members")
      .then((rows) => { setMembers(rows.filter((r) => r.status === "active")); })
      .catch(() => { setMembers([]); });
  }, [isAdmin, namedShares]);

  function toggle(userId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  const processing = docs?.some((d) => d.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => void load(), 2500);
    return () => { clearInterval(t); };
  }, [processing, load]);

  async function upload(files: FileList | File[]) {
    setError(null);
    setNotice(null);
    if (isAdmin && audience === "members" && selected.size === 0) {
      setError("Choose at least one member to share with, or pick another option.");
      if (input.current) input.current.value = "";
      return;
    }
    const list = Array.from(files);
    let ok = 0;
    for (const file of list) {
      setUploading(file.name);
      const form = new FormData();
      form.append("file", file);
      form.append("visibility", isAdmin && workspaceVisibility && audience === "workspace" ? "workspace" : "private");
      if (namedShares && isAdmin && audience === "members") for (const id of selected) form.append("share_with", id);
      if (namedShares && !isAdmin && shareWithAdmin) form.append("share_with", "admin");
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
          !workspaceVisibility && !namedShares
            ? "Documents you upload are private to you: only you can see them and ask questions over them."
            : isAdmin
              ? "Share each upload with the whole workspace, with selected members, or keep it to yourself. Documents members share with you appear here too."
              : "Documents you upload are private unless you share them with your admin. Documents your admin shares with you appear here too."
        }
      />

      <Card className="mb-6 p-5">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => { setDragging(false); }}
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
          <label className="mt-2 cursor-pointer rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover">
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
          {chooseAudience ? (
            <div className="mt-4 w-full max-w-xl">
              <p className="mb-1.5 text-xs font-medium text-ink-700">Who can use these documents?</p>
              <div className="inline-flex rounded-lg border border-ink-200 bg-surface p-0.5 text-xs" role="radiogroup" aria-label="Share with">
                {audiences.map(({ value, label, icon: Icon }) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={audience === value}
                    onClick={() => { setAudience(value); }}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium ${
                      audience === value ? "bg-inverse text-on-inverse" : "text-ink-600 hover:bg-surface-hover"
                    }`}
                  >
                    <Icon className="size-3.5" aria-hidden />
                    {label}
                  </button>
                ))}
              </div>
              {audience === "members" && (
                <div className="mt-3 rounded-lg border border-ink-200 bg-surface p-3 text-left">
                  {members.length === 0 ? (
                    <p className="text-xs text-ink-500">No active members yet. Approve members in Manage members first.</p>
                  ) : (
                    <>
                      <div className="mb-2 flex items-center justify-between text-xs">
                        <span className="text-ink-600">
                          {selected.size} of {members.length} selected
                        </span>
                        <button
                          type="button"
                          className="font-medium text-brand-700 hover:underline"
                          onClick={() => { setSelected(selected.size === members.length ? new Set() : new Set(members.map((m) => m.user_id))); }
                          }
                        >
                          {selected.size === members.length ? "Clear" : "Select all"}
                        </button>
                      </div>
                      <ul className="max-h-40 space-y-1 overflow-y-auto">
                        {members.map((m) => (
                          <li key={m.user_id}>
                            <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-surface-hover">
                              <input
                                type="checkbox"
                                checked={selected.has(m.user_id)}
                                onChange={() => { toggle(m.user_id); }}
                                className="size-4 rounded border-ink-300"
                              />
                              <span className="text-ink-900">{m.name || m.email}</span>
                              {m.name && <span className="truncate text-xs text-ink-500">{m.email}</span>}
                            </label>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}
            </div>
          ) : !isAdmin && namedShares ? (
            <label className="mt-4 flex max-w-md cursor-pointer items-start gap-2.5 rounded-lg border border-ink-200 bg-surface px-3 py-2.5 text-left">
              <input
                type="checkbox"
                checked={shareWithAdmin}
                onChange={(e) => { setShareWithAdmin(e.target.checked); }}
                className="mt-0.5 size-4 rounded border-ink-300"
              />
              <span>
                <span className="block text-sm font-medium text-ink-900">Share with my workspace admin</span>
                <span className="block text-xs text-ink-500">
                  {shareWithAdmin
                    ? "Your admin can see these documents in their library and ask questions over them."
                    : "Off: only you can see these documents. Your admin cannot open them."}
                </span>
              </span>
            </label>
          ) : null}
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
                      <Access d={d} />
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
