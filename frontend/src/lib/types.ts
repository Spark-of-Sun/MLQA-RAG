export type Role = "super_admin" | "admin" | "tenant";
export type MemberStatus = "pending" | "active" | "rejected" | "suspended";

export interface Me {
  user: { id: string; email: string | null; name: string | null };
  membership: null | {
    id: string;
    role: Role;
    status: MemberStatus;
    active: boolean;
    organization: { id: string; name: string; kind: "legal" | "medical" | "both"; status: string };
    workspace: null | { id: string; name: string; status: string };
  };
}

export interface DocumentRow {
  id: string;
  title: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  visibility: "workspace" | "private";
  status: "processing" | "ready" | "failed";
  error: string | null;
  notes: string | null;
  page_count: number | null;
  chunk_count: number | null;
  structure: "detected" | "fallback" | null;
  created_at: string;
  owner: string;
  mine: boolean;
}

export interface Check {
  code: string;
  label: string;
  ok: boolean;
  detail: string;
}

export type Segment =
  | { type: "sentence"; text: string; citations: number[]; checks: Check[] }
  | { type: "refusal"; text: string }
  | { type: "removed"; reason: string; checks: Check[] };

export interface Citation {
  n: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  highlights: [number, number][];
  text: string | null;
  unavailable?: boolean;
}

export interface Answer {
  id: string;
  question: string;
  created_at: string;
  outcome: "answered" | "partial" | "refused";
  segments: Segment[];
  citations: Citation[];
  stats: {
    verified: number;
    removed: number;
    sources_considered?: number;
    latency_ms?: number;
    model?: string;
  };
}

export interface HistoryItem {
  id: string;
  question: string;
  outcome: Answer["outcome"];
  created_at: string;
}

export interface CodeInfo {
  lookup_id: string;
  created_at: string;
  expires_at: string;
  max_uses: number;
  uses: number;
}

export interface NewCode extends CodeInfo {
  code: string;
}

export interface AdminRow {
  id: string;
  status: MemberStatus;
  created_at: string;
  email: string | null;
  name: string | null;
  last_seen_at: string | null;
  workspace_name: string;
  workspace_status: string;
  tenants: number;
  tenants_pending: number;
  documents: number;
  queries_30d: number;
}

export interface MemberRow {
  id: string;
  status: MemberStatus;
  created_at: string;
  email: string | null;
  name: string | null;
  last_seen_at: string | null;
  private_documents: number;
}

export interface AuditEvent {
  id: number;
  created_at: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  hash: string;
  actor_email: string | null;
  actor_name: string | null;
}
