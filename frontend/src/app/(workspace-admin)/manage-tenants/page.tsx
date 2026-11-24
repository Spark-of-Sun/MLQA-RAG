import type { Metadata } from "next";

import { ManageTenants } from "@/components/manage/manage-tenants";
import { requireMe } from "@/lib/backend";
import { hasFeature } from "@/lib/features";

export const metadata: Metadata = { title: "Manage members" };

export default async function ManageTenantsPage() {
  const me = await requireMe();
  return (
    <ManageTenants
      workspaceName={me.membership?.workspace?.name ?? ""}
      profiles={hasFeature(me, "profiles")}
      usage={hasFeature(me, "usage_counts")}
    />
  );
}
