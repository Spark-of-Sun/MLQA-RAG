import type { Metadata } from "next";

import { AuditLog } from "@/components/audit/audit-log";
import { EMPTY_FILTERS, type AuditFilters } from "@/lib/audit-filters";
import { requireMe } from "@/lib/backend";
import { hasFeature } from "@/lib/features";

export const metadata: Metadata = { title: "Audit trail" };

type Params = Record<string, string | string[] | undefined>;

// Filters live in the URL, so a filtered view can be bookmarked or reloaded.
function filtersFrom(params: Params): AuditFilters {
  const one = (key: string) => {
    const v = params[key];
    return (Array.isArray(v) ? v[0] : v)?.slice(0, 100) ?? "";
  };
  const day = (key: string) => (/^\d{4}-\d{2}-\d{2}$/.test(one(key)) ? one(key) : "");
  return {
    ...EMPTY_FILTERS,
    category: one("category") || "all",
    q: one("q"),
    action: one("action"),
    actor: one("actor"),
    from: day("from"),
    to: day("to"),
  };
}

export default async function AuditPage({ searchParams }: { searchParams: Promise<Params> }) {
  const me = await requireMe();
  const role = me.membership?.role ?? "tenant";
  return <AuditLog role={role} initial={filtersFrom(await searchParams)} chats={hasFeature(me, "chats")} />;
}
