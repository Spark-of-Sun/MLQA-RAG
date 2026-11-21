import type { Metadata } from "next";

import { ManageTenants } from "@/components/manage/manage-tenants";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Manage members" };

export default async function ManageTenantsPage() {
  const me = await requireMe();
  return <ManageTenants workspaceName={me.membership?.workspace?.name ?? ""} />;
}
