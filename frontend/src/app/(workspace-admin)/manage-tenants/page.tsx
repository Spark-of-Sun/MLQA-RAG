import { ManageTenants } from "@/components/ManageTenants";
import { Shell } from "@/components/Shell";
import { requireMe } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function ManageTenantsPage() {
  const me = await requireMe("/manage-tenants");
  return (
    <Shell me={me}>
      <h1 className="mb-4 text-xl font-semibold">Manage your team</h1>
      <ManageTenants />
    </Shell>
  );
}
