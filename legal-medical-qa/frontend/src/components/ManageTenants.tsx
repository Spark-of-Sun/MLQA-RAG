"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useResource } from "@/lib/use-resource";
import { Notice } from "@/components/Shell";
import { SecretOnce, Table } from "@/components/SecretOnce";

interface Tenant { user_id: string; state: string; reason: string | null; requested_at: string }
interface Matter { id: string; label: string }

export function ManageTenants() {
  const [grant, setGrant] = useState<Record<string, { matter: string; tier: number }>>({});
  const [secret, setSecret] = useState<string | null>(null);
  const [newMatter, setNewMatter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [data, load] = useResource(async () => {
    const [t, m] = await Promise.all([api<{ tenants: Tenant[] }>("/workspace/tenants"), api<{ matters: Matter[] }>("/workspace/matters")]);
    return { tenants: t.tenants, matters: m.matters };
  });
  const tenants = data?.tenants ?? [];
  const matters = data?.matters ?? [];

  async function run(action: () => Promise<unknown>, failure: string) {
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError(failure);
    }
  }

  const decide = (id: string, action: string) => {
    const g = grant[id];
    const body = action === "approve" && g?.matter ? { grants: [{ matter_id: g.matter, max_tier: g.tier }] } : undefined;
    return run(() => api(`/workspace/tenants/${id}/${action}`, { method: "POST", json: body }), `Could not ${action} this person.`);
  };

  const pending = tenants.filter((t) => t.state === "pending_approval");
  const others = tenants.filter((t) => t.state !== "pending_approval");
  return (
    <div className="space-y-6">
      {error && <Notice tone="error">{error}</Notice>}
      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="ac">
        <h2 id="ac" className="font-medium">Admin Code</h2>
        <p className="mt-1 text-sm text-slate-600">Team members join your workspace with this code and then wait for your approval. A new code retires the old one.</p>
        <button type="button" className="mt-3 rounded bg-indigo-700 px-3 py-1.5 text-white" onClick={() => void run(async () => setSecret((await api<{ code: string }>("/workspace/code", { method: "POST" })).code), "Could not generate a code.")}>Generate a new code</button>
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="pend">
        <h2 id="pend" className="mb-2 font-medium">Waiting for approval ({pending.length})</h2>
        {pending.length === 0 ? <p className="text-sm text-slate-500">No requests.</p> : (
          <Table head={["Person", "Requested", "Give access to", "Highest level", ""]}>
            {pending.map((t) => (
              <tr key={t.user_id} className="border-t border-slate-100">
                <td className="py-2 font-mono text-xs">{t.user_id.slice(0, 8)}</td>
                <td>{new Date(t.requested_at).toLocaleDateString()}</td>
                <td>
                  <select aria-label="Matter" className="rounded border border-slate-300 px-1" value={grant[t.user_id]?.matter ?? ""} onChange={(e) => setGrant({ ...grant, [t.user_id]: { matter: e.target.value, tier: grant[t.user_id]?.tier ?? 2 } })}>
                    <option value="">No matter yet</option>
                    {matters.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                  </select>
                </td>
                <td>
                  <select aria-label="Highest confidentiality level" className="rounded border border-slate-300 px-1" value={grant[t.user_id]?.tier ?? 2} onChange={(e) => setGrant({ ...grant, [t.user_id]: { matter: grant[t.user_id]?.matter ?? "", tier: Number(e.target.value) } })}>
                    {[1, 2, 3].map((n) => <option key={n} value={n}>Level {n}</option>)}
                  </select>
                </td>
                <td className="space-x-2 text-right">
                  <button type="button" className="underline" onClick={() => void decide(t.user_id, "approve")}>Approve</button>
                  <button type="button" className="underline" onClick={() => void decide(t.user_id, "reject")}>Reject</button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="team">
        <h2 id="team" className="mb-2 font-medium">Team</h2>
        {others.length === 0 ? <p className="text-sm text-slate-500">No members yet.</p> : (
          <Table head={["Person", "State", ""]}>
            {others.map((t) => (
              <tr key={t.user_id} className="border-t border-slate-100">
                <td className="py-2 font-mono text-xs">{t.user_id.slice(0, 8)}</td>
                <td>{t.state.replace("_", " ")}{t.reason ? ` (${t.reason.replace("_", " ")})` : ""}</td>
                <td className="text-right">
                  {t.state === "active" && <button type="button" className="underline" onClick={() => void decide(t.user_id, "suspend")}>Suspend</button>}
                  {t.state === "suspended" && t.reason !== "workspace_frozen" && <button type="button" className="underline" onClick={() => void decide(t.user_id, "reactivate")}>Reactivate</button>}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="mat">
        <h2 id="mat" className="mb-2 font-medium">Matters and patients</h2>
        <ul className="mb-3 list-disc pl-5 text-sm">{matters.map((m) => <li key={m.id}>{m.label}</li>)}</ul>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void run(() => api("/workspace/matters", { method: "POST", json: { label: newMatter } }), "Could not create it.").then(() => setNewMatter("")); }}>
          <label className="sr-only" htmlFor="mname">New matter</label>
          <input id="mname" required value={newMatter} onChange={(e) => setNewMatter(e.target.value)} placeholder="e.g. Smith v. Jones" className="flex-1 rounded border border-slate-300 px-3 py-1.5" />
          <button className="rounded border border-slate-300 px-3 py-1.5">Add</button>
        </form>
      </section>
      {secret && <SecretOnce label="Your new Admin Code" secret={secret.replaceAll("-", "")} onClose={() => setSecret(null)} />}
    </div>
  );
}
