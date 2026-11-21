// Shared by the audit page (server, reads the URL) and the audit log (client, edits the filters).
export interface AuditFilters {
  category: string;
  q: string;
  action: string;
  actor: string;
  from: string;
  to: string;
}

export const EMPTY_FILTERS: AuditFilters = { category: "all", q: "", action: "", actor: "", from: "", to: "" };
