"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useResource } from "@/lib/use-resource";
import { Notice } from "@/components/Shell";
import { Table } from "@/components/SecretOnce";

interface Wall { user_id: string; matter_id: string; reason: string; since: string }
interface Matter { id: string; label: string }
interface Tenant { user_id: string; state: string }

export function Walls() {
  const [user, setUser] = useState("");
  const [matter, setMatter] = useState("");
  const [reason, setReason] = useState("conflict");
  const [error, setError] = useState<string | null>(null);

  const [data, load] = useResource(async () => {
    const [w, m, t] = await Promise.all([
      api<{ walls: Wall[] }>("/workspace/walls"),
      api<{ matters: Matter[] }>("/workspace/matters"),
      api<{ tenants: Tenant[] }>("/workspace/tenants"),
    ]);
    return { walls: w.walls, matters: m.matters, tenants: t.tenants.filter((x) => x.state === "active") };
  });
  const walls = data?.walls ?? [];
  const matters = data?.matters ?? [];
  const tenants = data?.tenants ?? [];

  const label = (id: string) => matters.find((m) => m.id === id)?.label ?? id.slice(0, 8);
  return (
    <div className="space-y-6">
      <Notice>A wall blocks one person from one matter, beats every grant and even their own documents, and takes effect on their next request. Lifting a wall needs a second approver and is not available in this version.</Notice>
      {error && <Notice tone="error">{error}</Notice>}
      <form
        className="grid gap-3 rounded-lg bg-white p-4 shadow-sm sm:grid-cols-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          api("/workspace/walls", { method: "POST", json: { user_id: user, matter_id: matter, reason_code: reason } })
            .then(() => load())
            .catch((err: unknown) => { if (!(err instanceof ApiError && err.status === 401)) setError("Could not create the wall."); });
        }}
      >
        <label className="text-sm">Person
          <select required value={user} onChange={(e) => setUser(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1">
            <option value="">Choose…</option>
            {tenants.map((t) => <option key={t.user_id} value={t.user_id}>{t.user_id.slice(0, 8)}</option>)}
          </select>
        </label>
        <label className="text-sm">Matter
          <select required value={matter} onChange={(e) => setMatter(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1">
            <option value="">Choose…</option>
            {matters.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
        <label className="text-sm">Reason
          <select value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1">
            <option value="conflict">Conflict of interest</option>
            <option value="screening">Lateral hire screening</option>
            <option value="other">Other</option>
          </select>
        </label>
        <button className="self-end rounded bg-indigo-700 px-3 py-1.5 text-white">Create wall</button>
      </form>
      <section className="rounded-lg bg-white p-4 shadow-sm" aria-labelledby="w">
        <h2 id="w" className="mb-2 font-medium">Active walls</h2>
        {walls.length === 0 ? <p className="text-sm text-slate-500">None.</p> : (
          <Table head={["Person", "Matter", "Reason", "Since"]}>
            {walls.map((w) => (
              <tr key={`${w.user_id}-${w.matter_id}`} className="border-t border-slate-100">
                <td className="py-2 font-mono text-xs">{w.user_id.slice(0, 8)}</td>
                <td>{label(w.matter_id)}</td>
                <td>{w.reason}</td>
                <td>{new Date(w.since).toLocaleString()}</td>
              </tr>
            ))}
          </Table>
        )}
      </section>
    </div>
  );
}
