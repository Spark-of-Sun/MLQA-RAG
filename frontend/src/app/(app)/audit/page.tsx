import type { Metadata } from "next";

import { AuditLog } from "@/components/audit/audit-log";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Audit trail" };

export default async function AuditPage() {
  const me = await requireMe();
  const role = me.membership?.role ?? "tenant";
  return <AuditLog role={role} />;
}
