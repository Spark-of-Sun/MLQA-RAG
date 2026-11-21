import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { Library } from "@/components/library/library";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Library" };

export default async function LibraryPage() {
  const me = await requireMe();
  if (me.membership?.role === "super_admin") redirect("/manage-admins");
  return <Library isAdmin={me.membership?.role === "admin"} />;
}
