"use client";

import { UserCog } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CodePanel } from "@/components/manage/code-panel";
import { Alert, Button, Card, ConfirmButton, EmptyState, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { timeAgo } from "@/lib/format";
import type { AdminRow } from "@/lib/types";

export function ManageAdmins({ orgName }: { orgName: string }) {
  const [rows, setRows] = useState<AdminRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<AdminRow[]>("org/admins"));
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
      await api.post(`org/admins/${id}/${action}`);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const pending = rows?.filter((r) => r.status === "pending").length ?? 0;
  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <PageHeader
        title="Manage admins"
        subtitle={
          <>
            Each admin runs one isolated workspace in {orgName}. As Super Admin you approve and suspend admins and see usage
            totals, but never their documents, members or questions.
          </>
        }
      />
      <div className="space-y-6">
        <CodePanel kind="org" />
        {error && <Alert>{error}</Alert>}
        <Card>
          <div className="flex items-center justify-between border-b border-ink-100 px-5 py-3">
            <h2 className="font-semibold text-ink-950">Admins and workspaces</h2>
            {pending > 0 && <span className="text-xs font-medium text-amber-700">{pending} awaiting approval</span>}
          </div>
          {rows === null ? (
            <div className="p-6">
              <Spinner label="Loading…" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState icon={<UserCog className="size-5" />} title="No admins yet">
              Generate an Organization Code above and share it with the people who will run workspaces.
            </EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-ink-100 text-xs text-ink-500">
                  <tr>
                    <th className="px-5 py-3 font-medium">Admin</th>
                    <th className="px-3 py-3 font-medium">Workspace</th>
                    <th className="px-3 py-3 font-medium">Status</th>
                    <th className="px-3 py-3 text-right font-medium">Members</th>
                    <th className="px-3 py-3 text-right font-medium">Documents</th>
                    <th className="px-3 py-3 text-right font-medium">Questions (30 d)</th>
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
                      <td className="px-3 py-3 text-ink-700">{r.workspace_name}</td>
                      <td className="px-3 py-3">
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-ink-700">
                        {r.tenants}
                        {r.tenants_pending > 0 && <span className="text-xs text-amber-700"> +{r.tenants_pending}</span>}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-ink-700">{r.documents}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-ink-700">{r.queries_30d}</td>
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
            </div>
          )}
        </Card>
        <p className="text-xs text-ink-500">
          Suspending an admin freezes their workspace at once: the admin and its members lose access on their next request.
        </p>
      </div>
    </div>
  );
}
