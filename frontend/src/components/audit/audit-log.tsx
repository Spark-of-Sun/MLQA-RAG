"use client";

import { History, ShieldCheck, ShieldX } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, Button, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import type { AuditEvent, Role } from "@/lib/types";

const LABELS: Record<string, string> = {
  "org.created": "Organization created",
  "code.org.rotated": "Organization Code generated",
  "code.admin.rotated": "Member invite code generated",
  "code.rejected": "Code rejected",
  "admin.join_requested": "Admin requested to join",
  "admin.approve": "Admin approved",
  "admin.reject": "Admin rejected",
  "admin.suspend": "Admin suspended",
  "admin.reactivate": "Admin reactivated",
  "admin.request_withdrawn": "Admin request withdrawn",
  "tenant.join_requested": "Member requested to join",
  "tenant.approve": "Member approved",
  "tenant.reject": "Member rejected",
  "tenant.suspend": "Member suspended",
  "tenant.reactivate": "Member reactivated",
  "tenant.request_withdrawn": "Member request withdrawn",
  "document.uploaded": "Document uploaded",
  "document.indexed": "Document indexed",
  "document.failed": "Document failed to index",
  "document.deleted": "Document deleted",
  "query.answered": "Question answered",
};

function summary(e: AuditEvent): string {
  const p = e.payload;
  if (e.action === "query.answered") return `${p.outcome} · ${p.verified} verified, ${p.removed} removed`;
  if (e.action === "document.indexed") return `${p.chunks} passages`;
  if (e.action.startsWith("document.") && typeof p.title === "string") return p.title;
  if (e.action === "code.rejected") return `reason: ${String(p.reason)}`;
  if (e.action === "admin.join_requested" && typeof p.workspace === "string") return `workspace ${p.workspace}`;
  return "";
}

export function AuditLog({ role }: { role: Role }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [more, setMore] = useState(true);
  const [verify, setVerify] = useState<{ ok: boolean; events_in_scope: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (before?: number) => {
    try {
      const page = await api.get<AuditEvent[]>(`audit?limit=50${before ? `&before=${before}` : ""}`);
      setEvents((prev) => (before && prev ? [...prev, ...page] : page));
      setMore(page.length === 50);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function runVerify() {
    setBusy(true);
    try {
      setVerify(await api.get("audit/verify"));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const scope =
    role === "super_admin"
      ? "Organization-level events: organization, codes and admin decisions. Workspace content is never shown here."
      : role === "admin"
        ? "Every event in your workspace. Questions and answers are recorded as hashes, not text."
        : "Your own activity in this workspace.";

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader
        title="Audit trail"
        subtitle={scope}
        actions={
          role !== "tenant" && (
            <Button variant="secondary" busy={busy} onClick={runVerify}>
              <ShieldCheck className="size-4" aria-hidden /> Verify hash chain
            </Button>
          )
        }
      />
      {verify && (
        <div className="mb-4">
          {verify.ok ? (
            <Alert tone="green">
              <span className="inline-flex items-center gap-1.5 font-medium">
                <ShieldCheck className="size-4" aria-hidden /> Chain intact.
              </span>{" "}
              Every event was recomputed from the first one; nothing has been altered. {verify.events_in_scope} events in
              your view.
            </Alert>
          ) : (
            <Alert>
              <span className="inline-flex items-center gap-1.5 font-medium">
                <ShieldX className="size-4" aria-hidden /> Tampering detected.
              </span>{" "}
              An audit event no longer matches its hash. Contact your platform operator.
            </Alert>
          )}
        </div>
      )}
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <Card>
        {events === null ? (
          <div className="p-6">
            <Spinner label="Loading…" />
          </div>
        ) : events.length === 0 ? (
          <EmptyState icon={<History className="size-5" />} title="No events yet" />
        ) : (
          <ul className="divide-y divide-ink-100">
            {events.map((e) => (
              <li key={e.id} className="flex items-start gap-4 px-5 py-3">
                <span className="w-36 shrink-0 text-xs text-ink-500">{formatDate(e.created_at)}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink-900">{LABELS[e.action] ?? e.action}</p>
                  <p className="truncate text-xs text-ink-500">
                    {e.actor_name || e.actor_email || "System"}
                    {summary(e) ? ` · ${summary(e)}` : ""}
                  </p>
                </div>
                <code className="hidden shrink-0 text-[11px] text-ink-400 sm:block" title={e.hash}>
                  #{e.id} {e.hash.slice(0, 10)}
                </code>
              </li>
            ))}
          </ul>
        )}
        {events && more && (
          <div className="border-t border-ink-100 p-3 text-center">
            <Button variant="ghost" onClick={() => load(events.at(-1)?.id)}>
              Load older events
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
