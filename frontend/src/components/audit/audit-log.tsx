"use client";

import { ChevronDown, ChevronRight, ExternalLink, History, RotateCcw, Search, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Alert, Badge, Button, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { EMPTY_FILTERS, type AuditFilters } from "@/lib/audit-filters";
import { formatDate } from "@/lib/format";
import type { AdminRow, AuditEvent, ChainCheck, MemberRow, Role } from "@/lib/types";

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
  "profile.updated": "Profile updated",
  "document.uploaded": "Document uploaded",
  "document.indexed": "Document indexed",
  "document.failed": "Document failed to index",
  "document.deleted": "Document deleted",
  "conversation.created": "Chat started",
  "conversation.renamed": "Chat renamed",
  "conversation.deleted": "Chat deleted",
  "query.answered": "Question answered",
};

interface Section {
  key: string;
  label: string;
  prefixes: string[] | null;
  hint: string;
}

const SECTIONS: Record<Role, Section[]> = {
  tenant: [
    { key: "all", label: "All activity", prefixes: null, hint: "Everything about you in this workspace: membership, profile, library and chats." },
    { key: "library", label: "Library", prefixes: ["document."], hint: "Your uploads, indexing and deletions, and documents your admin shared with you." },
    { key: "chats", label: "Chats", prefixes: ["query.", "conversation."], hint: "Chats you started, renamed or deleted, and every question you asked. Questions are stored as hashes." },
  ],
  admin: [
    { key: "all", label: "All activity", prefixes: null, hint: "Every event in your workspace." },
    { key: "members", label: "Members", prefixes: ["tenant.", "profile."], hint: "Join requests, approvals, suspensions and profile changes." },
    { key: "library", label: "Library", prefixes: ["document."], hint: "Uploads, shares, indexing and deletions. Titles of members' private documents are hidden." },
    { key: "chats", label: "Questions & chats", prefixes: ["query.", "conversation."], hint: "Who asked how many questions and with what outcome. Questions and answers are hashes, never text." },
    { key: "codes", label: "Invite codes", prefixes: ["code."], hint: "Invite code rotations and rejected code attempts." },
  ],
  super_admin: [
    { key: "all", label: "All activity", prefixes: null, hint: "Organization-level events. Workspace content is never shown here." },
    { key: "admins", label: "Admins", prefixes: ["admin."], hint: "Admin join requests and decisions." },
    { key: "codes", label: "Organization Code", prefixes: ["code."], hint: "Code rotations and rejected code attempts." },
    { key: "organization", label: "Organization & profile", prefixes: ["org.", "profile."], hint: "Organization changes and your profile updates." },
  ],
};

const PAGE = 50;

function categoryOf(role: Role, action: string): Section | undefined {
  return SECTIONS[role].find((s) => s.prefixes?.some((p) => action.startsWith(p)));
}

function summary(e: AuditEvent): string {
  const p = e.payload;
  if (e.action === "query.answered") return `${String(p.outcome)} · ${String(p.verified)} verified, ${String(p.removed)} removed`;
  if (e.action.startsWith("document.")) {
    const title = typeof p.title === "string" ? p.title : "Private document";
    const parts = [title];
    if (e.action === "document.indexed") parts.push(`${String(p.chunks)} passages`);
    if (e.action === "document.failed") parts.push(`reason: ${String(p.reason)}`);
    if (e.action === "document.uploaded") {
      if (p.visibility === "workspace") parts.push("shared with the whole workspace");
      else if (e.shared_with_names?.length) parts.push(`shared with ${e.shared_with_names.join(", ")}`);
      else if (e.actor_is_me) parts.push("private");
    }
    return parts.join(" · ");
  }
  if (e.action === "profile.updated" && Array.isArray(p.fields)) return `changed ${p.fields.join(", ").replaceAll("_", " ")}`;
  if (e.action === "code.rejected") return `reason: ${String(p.reason)}`;
  if (e.action === "admin.join_requested" && typeof p.workspace === "string") return `workspace ${p.workspace}`;
  return "";
}

function chatLink(e: AuditEvent): string | null {
  if (!e.actor_is_me || e.action === "conversation.deleted") return null;
  const id = e.action.startsWith("conversation.") ? e.target_id : (e.payload.conversation_id as string | undefined);
  return id ? `/chat/${id}` : null;
}

function toQuery(f: AuditFilters, before?: number): string {
  const qs = new URLSearchParams({ limit: String(PAGE) });
  if (f.category !== "all") qs.set("category", f.category);
  if (f.q.trim()) qs.set("q", f.q.trim());
  if (f.action) qs.set("action", f.action);
  if (f.actor) qs.set("actor", f.actor);
  // Dates are the viewer's local days; the API takes instants.
  if (f.from) qs.set("since", new Date(`${f.from}T00:00:00`).toISOString());
  if (f.to) {
    const end = new Date(`${f.to}T00:00:00`);
    end.setDate(end.getDate() + 1);
    qs.set("until", end.toISOString());
  }
  if (before) qs.set("before", String(before));
  return qs.toString();
}

function syncUrl(f: AuditFilters) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v && !(k === "category" && v === "all")) qs.set(k, v);
  const url = `${window.location.pathname}${qs.size ? `?${qs}` : ""}`;
  window.history.replaceState(null, "", url);
}

const INPUT =
  "rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-800 focus:border-brand-400 focus:ring-2 focus:ring-brand-100 focus:outline-none";

export function AuditLog({ role, initial }: { role: Role; initial: AuditFilters }) {
  const sections = SECTIONS[role];
  const [filters, setFilters] = useState<AuditFilters>(() => ({
    ...initial,
    category: sections.some((s) => s.key === initial.category) ? initial.category : "all",
  }));
  const [search, setSearch] = useState(initial.q);
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [more, setMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [people, setPeople] = useState<{ id: string; label: string }[]>([]);
  const [verify, setVerify] = useState<ChainCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  const section: Section = sections.find((s) => s.key === filters.category) ?? sections[0]!;
  const actions = useMemo(
    () =>
      Object.keys(LABELS).filter((a) =>
        section.prefixes ? section.prefixes.some((p) => a.startsWith(p)) : sections.some((s) => s.prefixes?.some((p) => a.startsWith(p))),
      ),
    [section, sections],
  );
  const active = Object.entries(filters).filter(([k, v]) => v && !(k === "category")).length;

  const load = useCallback(async (f: AuditFilters, before?: number) => {
    const id = ++request.current;
    if (before) setLoadingMore(true);
    try {
      const page = await api.get<AuditEvent[]>(`audit?${toQuery(f, before)}`);
      if (id !== request.current) return; // a newer filter won
      setEvents((prev) => (before && prev ? [...prev, ...page] : page));
      setMore(page.length === PAGE);
      setError(null);
    } catch (e) {
      if (id === request.current) setError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    syncUrl(filters);
    setEvents(null);
    void load(filters);
  }, [filters, load]);

  // Free-text search waits for a pause in typing.
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f.q === search ? f : { ...f, q: search })), 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (role === "admin") {
      api
        .get<MemberRow[]>("workspace/members")
        .then((rows) => setPeople(rows.map((r) => ({ id: r.user_id, label: r.name || r.email || "Member" }))))
        .catch(() => setPeople([]));
    } else if (role === "super_admin") {
      api
        .get<AdminRow[]>("org/admins")
        .then((rows) => setPeople(rows.map((r) => ({ id: r.user_id, label: r.name || r.email || "Admin" }))))
        .catch(() => setPeople([]));
    }
  }, [role]);

  function set<K extends keyof AuditFilters>(key: K, value: AuditFilters[K]) {
    setFilters((f) => ({ ...f, [key]: value, ...(key === "category" ? { action: "" } : {}) }));
  }

  function reset() {
    setSearch("");
    setFilters({ ...EMPTY_FILTERS, category: filters.category });
  }

  async function runVerify() {
    setBusy(true);
    try {
      setVerify(await api.get<ChainCheck>("audit/verify"));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader
        title="Audit trail"
        subtitle="Every event is chained to the one before it by SHA-256, so any change to the history is detectable."
        actions={
          <Button variant="secondary" busy={busy} onClick={runVerify}>
            <ShieldCheck className="size-4" aria-hidden /> Verify hash chain
          </Button>
        }
      />
      {verify && (
        <div className="mb-4">
          {verify.ok ? (
            <Alert tone="green">
              <span className="inline-flex items-center gap-1.5 font-medium">
                <ShieldCheck className="size-4" aria-hidden /> Chain intact.
              </span>{" "}
              All {verify.checked} events of your organization were recomputed from the first one and nothing has been
              altered. {verify.events_in_scope} of them are in your view.
            </Alert>
          ) : (
            <Alert>
              <span className="inline-flex items-center gap-1.5 font-medium">
                <ShieldX className="size-4" aria-hidden /> Tampering detected.
              </span>{" "}
              An audit event no longer matches its hash{verify.first_bad_id ? ` (event #${verify.first_bad_id})` : ""}. Contact
              your platform operator.
            </Alert>
          )}
        </div>
      )}

      <div className="mb-3 flex flex-wrap gap-1 border-b border-ink-200" role="tablist" aria-label="Audit sections">
        {sections.map((s) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={filters.category === s.key}
            onClick={() => set("category", s.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              filters.category === s.key
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-800"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      <p className="mb-3 text-xs text-ink-500">{section.hint}</p>

      <Card className="mb-4 p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="relative min-w-52 flex-1">
            <span className="sr-only">Search</span>
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-ink-400" aria-hidden />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search person, document title, outcome…"
              className={`${INPUT} w-full pl-8`}
            />
          </label>
          <label className="text-xs text-ink-500">
            <span className="mb-0.5 block">Event</span>
            <select value={filters.action} onChange={(e) => set("action", e.target.value)} className={INPUT}>
              <option value="">All events</option>
              {actions.map((a) => (
                <option key={a} value={a}>
                  {LABELS[a]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ink-500">
            <span className="mb-0.5 block">Person</span>
            <select value={filters.actor} onChange={(e) => set("actor", e.target.value)} className={INPUT}>
              <option value="">Anyone</option>
              <option value="me">Me</option>
              <option value="others">{role === "tenant" ? "My admin" : "Everyone but me"}</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ink-500">
            <span className="mb-0.5 block">From</span>
            <input type="date" value={filters.from} max={filters.to || undefined} onChange={(e) => set("from", e.target.value)} className={INPUT} />
          </label>
          <label className="text-xs text-ink-500">
            <span className="mb-0.5 block">To</span>
            <input type="date" value={filters.to} min={filters.from || undefined} onChange={(e) => set("to", e.target.value)} className={INPUT} />
          </label>
          <Button variant="ghost" onClick={reset} disabled={active === 0 && !search}>
            <RotateCcw className="size-4" aria-hidden /> Reset
          </Button>
        </div>
      </Card>

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
          <EmptyState icon={<History className="size-5" />} title={active ? "No events match these filters" : "No events yet"}>
            {active ? "Change or reset the filters above." : null}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-ink-100">
            {events.map((e) => {
              const expanded = open === e.id;
              const cat = filters.category === "all" ? categoryOf(role, e.action) : undefined;
              const link = chatLink(e);
              return (
                <li key={e.id}>
                  <button
                    type="button"
                    onClick={() => setOpen(expanded ? null : e.id)}
                    aria-expanded={expanded}
                    className="flex w-full items-start gap-4 px-5 py-3 text-left hover:bg-ink-50/60"
                  >
                    {expanded ? (
                      <ChevronDown className="mt-0.5 size-4 shrink-0 text-ink-400" aria-hidden />
                    ) : (
                      <ChevronRight className="mt-0.5 size-4 shrink-0 text-ink-400" aria-hidden />
                    )}
                    <span className="w-36 shrink-0 text-xs text-ink-500">{formatDate(e.created_at)}</span>
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink-900">
                        {LABELS[e.action] ?? e.action}
                        {cat && <Badge>{cat.label}</Badge>}
                      </p>
                      <p className="truncate text-xs text-ink-500">
                        {e.actor_is_me ? "You" : e.actor_name || e.actor_email || "System"}
                        {summary(e) ? ` · ${summary(e)}` : ""}
                      </p>
                    </div>
                    <code className="hidden shrink-0 text-[11px] text-ink-400 sm:block" title={e.hash}>
                      #{e.id} {e.hash.slice(0, 10)}
                    </code>
                  </button>
                  {expanded && (
                    <dl className="mx-5 mb-3 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 rounded-lg bg-ink-50 px-4 py-3 text-xs">
                      <dt className="text-ink-500">Event</dt>
                      <dd className="font-mono text-ink-800">
                        #{e.id} {e.action}
                      </dd>
                      <dt className="text-ink-500">By</dt>
                      <dd className="text-ink-800">
                        {e.actor_name || "System"}
                        {e.actor_email ? ` <${e.actor_email}>` : ""}
                      </dd>
                      {e.target_type && (
                        <>
                          <dt className="text-ink-500">Target</dt>
                          <dd className="font-mono break-all text-ink-800">
                            {e.target_type} {e.target_id}
                          </dd>
                        </>
                      )}
                      {Object.entries(e.payload)
                        .filter(([, v]) => !(Array.isArray(v) && v.length === 0))
                        .map(([k, v]) => (
                          <div key={k} className="contents">
                            <dt className="text-ink-500">{k.replaceAll("_", " ")}</dt>
                            <dd className="font-mono break-all text-ink-800">
                              {k === "shared_with" && e.shared_with_names ? e.shared_with_names.join(", ") : typeof v === "string" ? v : JSON.stringify(v)}
                            </dd>
                          </div>
                        ))}
                      <dt className="text-ink-500">Hash</dt>
                      <dd className="font-mono break-all text-ink-800">{e.hash}</dd>
                      <dt className="text-ink-500">Previous hash</dt>
                      <dd className="font-mono break-all text-ink-500">{e.prev_hash}</dd>
                      {link && (
                        <>
                          <dt />
                          <dd>
                            <Link href={link} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
                              Open this chat <ExternalLink className="size-3" aria-hidden />
                            </Link>
                          </dd>
                        </>
                      )}
                    </dl>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {events && more && (
          <div className="border-t border-ink-100 p-3 text-center">
            <Button variant="ghost" busy={loadingMore} onClick={() => load(filters, events.at(-1)?.id)}>
              Load older events
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
