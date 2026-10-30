"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useResource } from "@/lib/use-resource";
import { Notice } from "@/components/Shell";
import { SecretOnce, Table } from "@/components/SecretOnce";

interface Admin {
  user_id: string;
  state: string;
  reason: string | null;
  requested_at: string;
  workspace_state: string;
  tenant_count: number;
  document_count: number;
}

const ACTIONS: Record<string, [string, string][]> = {
  pending_approval: [["approve", "Approve"], ["reject", "Reject"]],
  active: [["suspend", "Suspend"]],
  suspended: [["reactivate", "Reactivate"]],
};

export function ManageAdmins() {
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [data, load] = useResource(async () => (await api<{ admins: Admin[] }>("/org/admins")).admins);
  const admins = data ?? [];

  async function act(id: string, action: string) {
    setError(null);
    try {
      await api(`/org/admins/${id}/${action}`, { method: "POST" }); // step-up is requested automatically if the session is stale
      load();
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError(e instanceof ApiError ? `Could not ${action} (${e.title}).` : "Something went wrong.");
    }
  }

  async function newCode() {
    setError(null);
    try {
      setSecret((await api<{ code: string }>("/org/code", { method: "POST" })).code);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError("Could not generate the code. Is your organization active?");
    }
  }

  const pending = admins.filter((a) => a.state === "pending_approval");
  const rest = admins.filter((a) => a.state !== "pending_approval");
  return (
    <div className="space-y-6">
      {error && <Notice tone="error">{error}</Notice>}
      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="code">
        <h2 id="code" className="font-medium">Organization Code</h2>
        <p className="mt-1 text-sm text-slate-600">Share it with someone who should administer a workspace. Generating a new one retires the old one at once. Approvals still come to you.</p>
        <button type="button" onClick={() => void newCode()} className="mt-3 rounded bg-indigo-700 px-3 py-1.5 text-white">Generate a new code</button>
      </section>
      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="pending">
        <h2 id="pending" className="mb-2 font-medium">Waiting for your approval ({pending.length})</h2>
        {pending.length === 0 ? <p className="text-sm text-slate-500">No requests.</p> : <Rows admins={pending} act={act} />}
      </section>
      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="admins">
        <h2 id="admins" className="mb-2 font-medium">Administrators</h2>
        <p className="mb-2 text-xs text-slate-500">You see counts only. Tenants and documents are never shown to you.</p>
        {rest.length === 0 ? <p className="text-sm text-slate-500">None yet.</p> : <Rows admins={rest} act={act} />}
      </section>
      {secret && <SecretOnce label="Your new Organization Code" secret={secret.replaceAll("-", "")} onClose={() => setSecret(null)} />}
    </div>
  );
}

function Rows({ admins, act }: { admins: Admin[]; act: (id: string, action: string) => Promise<void> }) {
  return (
    <Table head={["Administrator", "State", "Tenants", "Documents", ""]}>
      {admins.map((a) => (
        <tr key={a.user_id} className="border-t border-slate-100">
          <td className="py-2 font-mono text-xs">{a.user_id.slice(0, 8)}</td>
          <td>{a.state.replace("_", " ")}{a.reason ? ` (${a.reason.replace("_", " ")})` : ""}</td>
          <td>{a.tenant_count}</td>
          <td>{a.document_count}</td>
          <td className="space-x-2 text-right">
            {(ACTIONS[a.state] ?? []).map(([action, label]) => (
              <button key={action} type="button" className="underline" onClick={() => { if (action === "suspend" && !window.confirm("Suspending freezes this workspace and signs out all its members within seconds.")) return; void act(a.user_id, action); }}>{label}</button>
            ))}
          </td>
        </tr>
      ))}
    </Table>
  );
}
