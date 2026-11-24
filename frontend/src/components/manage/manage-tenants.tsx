"use client";

import { Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CodePanel } from "@/components/manage/code-panel";
import { Alert, Button, Card, ConfirmButton, EmptyState, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate, formatTokens, timeAgo } from "@/lib/format";
import type { MemberRow } from "@/lib/types";

/**
 * Profile details and usage counts are frozen MVP-only features (`profiles`, `usage_counts`, DEV-21): while a flag
 * is off the gateway does not send those fields and these screens do not show them.
 */
type Shown = { profiles: boolean; usage: boolean };

function sharedBy(m: MemberRow): string {
  const byName = m.shared_with_them ?? 0;
  const workspace = m.shared_with_workspace ?? 0;
  return `${byName + workspace} (${byName} to them by name, ${workspace} with the whole workspace)`;
}

function MemberDetails({ m, shown, onClose }: { m: MemberRow; shown: Shown; onClose: () => void }) {
  const profile: [string, string | number][] = shown.profiles
    ? [
        ["Job title", m.job_title ?? "—"],
        ["Department", m.department ?? "—"],
        ["Phone", m.phone ?? "—"],
      ]
    : [];
  const rows: [string, string | number][] = [
    ["Email", m.email ?? "—"],
    ...profile,
    ["Status", m.status],
    ["Requested", formatDate(m.created_at)],
    ["Decided", formatDate(m.decided_at)],
    ["Last active", timeAgo(m.last_seen_at)],
  ];
  const usage: [string, string | number][] = [
    ["Documents uploaded", m.documents ?? 0],
    ["Private documents", m.private_documents ?? 0],
    ["Shared with you", m.shared_with_you ?? 0],
    ["Shared by you", sharedBy(m)],
    ["Questions asked", m.questions ?? 0],
    ["Approximate tokens", formatTokens(m.tokens ?? 0)],
    ["Last question", m.last_question_at ? formatDate(m.last_question_at) : "never"],
  ];
  return (
    <Modal title={m.name || m.email || "Member"} onClose={onClose}>
      <h3 className="text-xs font-semibold tracking-wide text-ink-500 uppercase">{shown.profiles ? "Profile" : "Member"}</h3>
      <dl className="mt-2 grid grid-cols-[9rem_1fr] gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-500">{k}</dt>
            <dd className="break-words text-ink-900">{v}</dd>
          </div>
        ))}
      </dl>
      {shown.usage && (
        <>
          <h3 className="mt-5 text-xs font-semibold tracking-wide text-ink-500 uppercase">Usage</h3>
          <dl className="mt-2 grid grid-cols-[9rem_1fr] gap-y-1.5 text-sm">
            {usage.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-500">{k}</dt>
                <dd className="text-ink-900 tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <p className="mt-4 text-xs text-ink-500">
        {shown.usage ? "You see counts only. " : ""}Their questions, answers, chats and private documents stay private to
        them; documents they share with you appear in your library.
      </p>
    </Modal>
  );
}

export function ManageTenants({ workspaceName, profiles, usage }: { workspaceName: string } & Shown) {
  const shown: Shown = { profiles, usage };
  const [rows, setRows] = useState<MemberRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<MemberRow | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<MemberRow[]>("workspace/members"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(id: string, action: string) {
    setError(null);
    try {
      await api.post(`workspace/members/${id}/${action}`);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <PageHeader
        title="Manage members"
        subtitle={
          <>
            Members of {workspaceName} can ask questions over the documents you share and upload documents of their own.
            You see a member&apos;s documents only if they share them with you. Click a member for their details.
          </>
        }
      />
      <div className="space-y-6">
        <CodePanel kind="admin" />
        {error && <Alert>{error}</Alert>}
        <Card>
          <div className="border-b border-ink-100 px-5 py-3">
            <h2 className="font-semibold text-ink-950">Members</h2>
          </div>
          {rows === null ? (
            <div className="p-6">
              <Spinner label="Loading…" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState icon={<Users className="size-5" />} title="No members yet">
              Generate an invite code above and share it, or copy the invite link.
            </EmptyState>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-ink-100 text-xs text-ink-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Member</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  {usage && (
                    <>
                      <th className="px-3 py-3 text-right font-medium" title="Documents only the member can see. You see the count, never the documents.">
                        Private documents
                      </th>
                      <th className="px-3 py-3 text-right font-medium" title="Documents this member shared with you">
                        Shared with you
                      </th>
                      <th className="px-3 py-3 text-right font-medium" title="Documents you shared with this member: by name, plus everything you shared with the whole workspace">
                        Shared by you
                      </th>
                      <th className="px-3 py-3 text-right font-medium">Questions</th>
                      <th className="px-3 py-3 text-right font-medium" title="Approximate model tokens used by their questions">
                        Tokens
                      </th>
                    </>
                  )}
                  <th className="px-3 py-3 font-medium">Last active</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {rows.map((r) => (
                  <tr key={r.id} className={r.status === "pending" ? "bg-amber-50/40" : undefined}>
                    <td className="px-5 py-3">
                      <button type="button" onClick={() => { setDetails(r); }} className="text-left hover:underline">
                        <span className="block font-medium text-ink-900">{r.name || r.email}</span>
                      </button>
                      <p className="text-xs text-ink-500">
                        {[profiles ? r.job_title : null, r.name ? r.email : null].filter(Boolean).join(" · ")}
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                    {usage && (
                      <>
                        <td className="px-3 py-3 text-right tabular-nums text-ink-700">{r.private_documents ?? 0}</td>
                        <td className="px-3 py-3 text-right tabular-nums text-ink-700">{r.shared_with_you ?? 0}</td>
                        <td className="px-3 py-3 text-right tabular-nums text-ink-700">
                          {(r.shared_with_them ?? 0) + (r.shared_with_workspace ?? 0)}
                          <span className="block text-[11px] text-ink-400">
                            {r.shared_with_them ?? 0} by name · {r.shared_with_workspace ?? 0} workspace
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums text-ink-700">{r.questions ?? 0}</td>
                        <td className="px-3 py-3 text-right text-xs tabular-nums text-ink-600">{formatTokens(r.tokens ?? 0)}</td>
                      </>
                    )}
                    <td className="px-3 py-3 text-xs text-ink-500">{timeAgo(r.last_seen_at)}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-2">
                        {r.status === "pending" && (
                          <>
                            <Button className="px-2.5 py-1.5 text-xs" onClick={() => act(r.id, "approve")}>
                              Approve
                            </Button>
                            <ConfirmButton label="Reject" onConfirm={() => act(r.id, "reject")} />
                          </>
                        )}
                        {r.status === "active" && <ConfirmButton label="Suspend" onConfirm={() => act(r.id, "suspend")} />}
                        {r.status === "suspended" && (
                          <Button variant="secondary" className="px-2.5 py-1.5 text-xs" onClick={() => act(r.id, "reactivate")}>
                            Reactivate
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        {usage && <p className="text-xs text-ink-400">
          Private documents are counted only; you cannot open them. Shared by you counts documents you shared with that
          member by name plus the documents you shared with the whole workspace. Questions counts every question asked, not chats. Tokens are approximate: what the model reported for answering,
          rewriting follow-ups and checking answers; search embeddings are not included.
        </p>}
      </div>
      {details && <MemberDetails m={details} shown={shown} onClose={() => { setDetails(null); }} />}
    </div>
  );
}
