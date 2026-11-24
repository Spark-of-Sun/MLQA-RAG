export type Role = "super_admin" | "admin" | "tenant";
export type MemberStatus = "pending" | "active" | "rejected" | "suspended";

export interface Me {
  /** Feature flags enabled on the server (contracts/features.toml); hidden screens still 404 on the server. */
  features?: string[];
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
  owner_role: "admin" | "tenant";
  mine: boolean;
  /** workspace: everyone in the workspace; shared: named people; private: the owner only. */
  access: "workspace" | "shared" | "private";
  shared_by: "you" | "admin" | "member" | null;
  shared_with: { id: string; name: string; role: "admin" | "tenant" }[];
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
  standalone_question?: string;
  /** null while the frozen `chats` feature is off: every question stands alone. */
  conversation_id: string | null;
  conversation_title?: string | null;
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
    pipeline?: Pipeline;
  };
}

/** How the passages behind an answer were found (absent on answers made before retrieval reported it). */
export interface Pipeline {
  queries?: number;
  alternatives?: string[];
  candidates?: number;
  reranked?: number;
  rerank?: "on" | "off" | "failed";
  rerank_model?: string | null;
  neighbours?: number;
  kept?: number;
  plan_ms?: number;
  embed_ms?: number;
  search_ms?: number;
  rerank_ms?: number;
  draft_ms?: number;
  verify_ms?: number;
  /** step -> "model · key <fingerprint>": which model and which API key (by SHA-256 fingerprint) served it */
  calls?: Record<string, string>;
}

export interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: number;
}

export interface ChatDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: Answer[];
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
  user_id: string;
  status: MemberStatus;
  created_at: string;
  email: string | null;
  name: string | null;
  last_seen_at: string | null;
  workspace_name: string;
  workspace_status: string;
  tenants: number;
  tenants_pending: number;
  /** Usage counts: sent only while the frozen `usage_counts` feature is on. */
  documents?: number;
  queries_30d?: number;
}

export interface MemberRow {
  id: string;
  user_id: string;
  status: MemberStatus;
  created_at: string;
  decided_at: string | null;
  email: string | null;
  name: string | null;
  last_seen_at: string | null;
  /** Profile details: sent only while the frozen `profiles` feature is on. */
  job_title?: string | null;
  department?: string | null;
  phone?: string | null;
  profile_updated_at?: string | null;
  /** Usage counts: sent only while the frozen `usage_counts` feature is on. */
  documents?: number;
  private_documents?: number;
  shared_with_you?: number;
  shared_with_them?: number;
  shared_with_workspace?: number;
  questions?: number;
  tokens?: number;
  last_question_at?: string | null;
}

export interface Profile {
  email: string | null;
  name: string | null;
  job_title: string | null;
  department: string | null;
  phone: string | null;
  profile_updated_at: string | null;
  created_at: string;
  joined_at: string;
  approved_at: string | null;
  role: Role;
  organization: string;
  workspace: string | null;
}

export interface AuditEvent {
  id: number;
  created_at: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  hash: string;
  prev_hash: string;
  actor_email: string | null;
  actor_name: string | null;
  actor_is_me: boolean;
  shared_with_names?: string[];
}

export interface ChainCheck {
  ok: boolean;
  checked: number;
  events_in_scope: number;
  first_bad_id: number | null;
}
