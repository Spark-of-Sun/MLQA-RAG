import { notFound, redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { requireMe } from "@/lib/backend";

// Workspace admin only; every other role gets 404 (blueprint 17.1).
export default async function WorkspaceAdminLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  if (!me.membership?.active) redirect("/onboarding");
  if (me.membership.role !== "admin") notFound();
  return <AppShell me={me}>{children}</AppShell>;
}
