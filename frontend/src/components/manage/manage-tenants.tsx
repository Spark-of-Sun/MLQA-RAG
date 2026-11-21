"use client";

import { Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CodePanel } from "@/components/manage/code-panel";
import { Alert, Button, Card, ConfirmButton, EmptyState, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { timeAgo } from "@/lib/format";
import type { MemberRow } from "@/lib/types";

export function ManageTenants({ workspaceName }: { workspaceName: string }) {
  const [rows, setRows] = useState<MemberRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader
        title="Manage members"
        subtitle={
          <>
            Members of {workspaceName} can ask questions over the documents you share and upload private documents of their
            own. You cannot read their private documents.
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
                  <th className="px-3 py-3 text-right font-medium">Private documents</th>
                  <th className="px-3 py-3 font-medium">Last active</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {rows.map((r) => (
                  <tr key={r.id} className={r.status === "pending" ? "bg-amber-50/40" : undefined}>
                    <td className="px-5 py-3">
                      <p className="font-medium text-ink-900">{r.name || r.email}</p>
                      {r.name && <p className="text-xs text-ink-500">{r.email}</p>}
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-ink-700">{r.private_documents}</td>
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
      </div>
    </div>
  );
}
