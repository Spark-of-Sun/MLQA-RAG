"use client";

import { Scale } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, Button, EmptyState, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";

interface RequestRow {
  id: string;
  kind: string;
  state: string;
  reason_code: string;
  target_type: string;
  target_id: string;
  created_at: string;
  wait_until: string | null;
  expires_at: string;
  approvals: number;
  approvals_required: number;
}

const KIND_LABEL: Record<string, string> = {
  successor_transfer: "Successor transfer",
  private_read_enable: "Enable admin private reading",
  wall_lift: "Lift an ethical wall",
  workspace_unseal: "Unseal a workspace",
  workspace_destroy: "Destroy a workspace",
  org_delete: "Delete the organization",
  owner_recovery: "Owner recovery",
  co_owner_set: "Add a co-owner",
};

// Two people and a waiting window for every action here (blueprint 6.7). Approving needs a fresh passkey
// sign-in; the server answers with a step-up challenge otherwise, and the client signs in again.
export function GovernanceCenter({ title }: { title: string }) {
  const [rows, setRows] = useState<RequestRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<RequestRow[]>("governance"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function act(id: string, action: "approve" | "reject" | "cancel") {
    setError(null);
    try {
      await api.post(`governance/${id}/${action}`);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader title={title} subtitle="Requests that need a second person and a waiting period. The person who starts a request can always cancel it." />
      {error && <Alert>{error}</Alert>}
      {rows === null ? <Spinner label="Loading requests" /> : rows.length === 0 ? (
        <EmptyState icon={<Scale aria-hidden />} title="No governance requests" />
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead><tr className="text-left text-ink-500"><th className="py-2">Request</th><th>Reason</th><th>Approvals</th><th>Wait until</th><th>Expires</th><th>State</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-ink-100">
                <td className="py-2"><div className="font-medium text-ink-900">{KIND_LABEL[r.kind] ?? r.kind}</div>
                  <div className="text-xs text-ink-500">{r.target_type} {r.target_id}</div></td>
                <td>{r.reason_code.replaceAll("_", " ")}</td>
                <td className="tabular-nums">{r.approvals} of {r.approvals_required}</td>
                <td>{r.wait_until ? formatDate(r.wait_until) : "—"}</td>
                <td>{formatDate(r.expires_at)}</td>
                <td><StatusBadge status={r.state} /></td>
                <td className="space-x-1 text-right whitespace-nowrap">
                  {r.state === "requested" && <>
                    <Button variant="secondary" onClick={() => void act(r.id, "approve")}>Approve</Button>
                    <Button variant="ghost" onClick={() => void act(r.id, "reject")}>Reject</Button>
                  </>}
                  {["requested", "approved", "waiting", "executable"].includes(r.state) &&
                    <Button variant="ghost" onClick={() => void act(r.id, "cancel")}>Cancel</Button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
