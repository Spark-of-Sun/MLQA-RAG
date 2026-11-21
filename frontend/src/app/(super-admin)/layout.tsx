import { notFound, redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { requireMe } from "@/lib/backend";

// Super Admin only; every other role gets 404 so the route is not revealed (blueprint 17.1).
export default async function SuperAdminLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  if (!me.membership?.active) redirect("/onboarding");
  if (me.membership.role !== "super_admin") notFound();
  return <AppShell me={me}>{children}</AppShell>;
}
