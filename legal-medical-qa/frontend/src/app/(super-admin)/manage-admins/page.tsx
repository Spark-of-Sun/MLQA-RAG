import { ManageAdmins } from "@/components/ManageAdmins";
import { Shell } from "@/components/Shell";
import { requireMe } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function ManageAdminsPage() {
  const me = await requireMe("/manage-admins");
  return (
    <Shell me={me}>
      <h1 className="mb-4 text-xl font-semibold">Manage administrators</h1>
      <ManageAdmins />
    </Shell>
  );
}
