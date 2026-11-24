"use client";

import { Briefcase, ShieldOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, Button, Card, EmptyState, Modal, PageHeader, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import type { MemberRow } from "@/lib/types";

interface MatterRow {
  id: string;
  label: string;
  kind: "matter" | "patient";
  created_at: string;
  closed_at: string | null;
  grants: number;
  walls: number;
}

const TIERS = [
  [1, "1 · Internal"],
  [2, "2 · Confidential"],
  [3, "3 · Privileged or PHI"],
  [4, "4 · Restricted"],
] as const;
const WALL_REASONS = ["conflict_of_interest", "lateral_hire", "client_instruction", "personal_relationship", "other"];

function MatterActions({ matter, members, onClose, onChanged }: {
  matter: MatterRow; members: MemberRow[]; onClose: () => void; onChanged: () => void;
}) {
  const [user, setUser] = useState("");
  const [tier, setTier] = useState(2);
  const [reason, setReason] = useState(WALL_REASONS[0]);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const tenants = members.filter((m) => m.status === "active");

  async function run(action: () => Promise<unknown>, message: string) {
    setError(null);
    setDone(null);
    try {
      await action();
      setDone(message);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <Modal title={matter.label} onClose={onClose}>
      <label className="block text-sm font-medium text-ink-700" htmlFor="matter-user">Member</label>
      <select id="matter-user" className="mt-1 w-full rounded-md border border-ink-200 p-2 text-sm" value={user}
        onChange={(e) => { setUser(e.target.value); }}>
        <option value="">Choose a member…</option>
        {tenants.map((m) => <option key={m.user_id} value={m.user_id}>{m.name || m.email}</option>)}
      </select>
      <fieldset className="mt-4">
        <legend className="text-sm font-medium text-ink-700">Grant access up to tier</legend>
        <select className="mt-1 w-full rounded-md border border-ink-200 p-2 text-sm" value={tier}
          onChange={(e) => { setTier(Number(e.target.value)); }} aria-label="Highest tier">
          {TIERS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <Button className="mt-2" disabled={!user}
          onClick={() => run(() => api.post(`workspace/matters/${matter.id}/grants`, { user_id: user, max_tier: tier }),
            "Access granted.")}>Grant access</Button>
      </fieldset>
      <fieldset className="mt-5 border-t border-ink-100 pt-4">
        <legend className="text-sm font-medium text-ink-700">Ethical wall</legend>
        <p className="mt-1 text-xs text-ink-500">A wall denies this member everything in the matter, even documents they
          own. It takes effect on their next request. Lifting a wall needs a second approver.</p>
        <select className="mt-2 w-full rounded-md border border-ink-200 p-2 text-sm" value={reason}
          onChange={(e) => { setReason(e.target.value); }} aria-label="Reason">
          {WALL_REASONS.map((r) => <option key={r} value={r}>{r.replaceAll("_", " ")}</option>)}
        </select>
        <Button className="mt-2" variant="danger" disabled={!user}
          onClick={() => run(() => api.post(`workspace/matters/${matter.id}/walls`, { user_id: user, reason_code: reason }),
            "Wall created.")}>Create wall</Button>
      </fieldset>
      <div aria-live="polite" className="mt-3">
        {error && <Alert>{error}</Alert>}
        {done && <Alert tone="green">{done}</Alert>}
      </div>
    </Modal>
  );
}

export function Matters() {
  const [rows, setRows] = useState<MatterRow[] | null>(null);
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"matter" | "patient">("matter");
  const [open, setOpen] = useState<MatterRow | null>(null);

  const load = useCallback(async () => {
    try {
      const [m, mem] = await Promise.all([api.get<MatterRow[]>("workspace/matters"), api.get<MemberRow[]>("workspace/members")]);
      setRows(m);
      setMembers(mem);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function create() {
    setError(null);
    try {
      await api.post("workspace/matters", { label, kind });
      setLabel("");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader title="Matters and walls" subtitle="Matters (or patients) group documents. Members see a matter's documents only with a grant whose tier covers them." />
      <Card className="p-4">
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <label className="flex-1 text-sm">
            <span className="font-medium text-ink-700">New matter or patient</span>
            <input className="mt-1 w-full rounded-md border border-ink-200 p-2" value={label} maxLength={200}
              onChange={(e) => { setLabel(e.target.value); }} required />
          </label>
          <select className="rounded-md border border-ink-200 p-2 text-sm" value={kind} aria-label="Kind"
            onChange={(e) => { setKind(e.target.value as "matter" | "patient"); }}>
            <option value="matter">Matter</option>
            <option value="patient">Patient</option>
          </select>
          <Button type="submit" disabled={!label.trim()}>Create</Button>
        </form>
      </Card>
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
      {rows === null ? <Spinner label="Loading matters" /> : rows.length === 0 ? (
        <EmptyState icon={<Briefcase aria-hidden />} title="No matters yet">Create one above, then grant members access.</EmptyState>
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead><tr className="text-left text-ink-500"><th className="py-2">Name</th><th>Kind</th><th>Grants</th><th>Walls</th><th>Created</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-ink-100">
                <td className="py-2 font-medium text-ink-900">{r.label}</td>
                <td>{r.kind}</td>
                <td className="tabular-nums">{r.grants}</td>
                <td className="tabular-nums">{r.walls > 0 ? <span className="inline-flex items-center gap-1"><ShieldOff className="h-3.5 w-3.5" aria-hidden />{r.walls}</span> : 0}</td>
                <td>{formatDate(r.created_at)}</td>
                <td className="text-right"><Button variant="secondary" onClick={() => { setOpen(r); }}>Manage</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && <MatterActions matter={open} members={members} onClose={() => { setOpen(null); }} onChanged={() => void load()} />}
    </div>
  );
}
