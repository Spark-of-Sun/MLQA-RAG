import type { Metadata } from "next";

import { ManageAdmins } from "@/components/manage/manage-admins";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Manage admins" };

export default async function ManageAdminsPage() {
  const me = await requireMe();
  return <ManageAdmins orgName={me.membership?.organization.name ?? ""} />;
}
