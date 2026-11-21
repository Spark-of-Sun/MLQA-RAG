import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { requireMe } from "@/lib/backend";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  if (!me.membership?.active) redirect("/onboarding");
  return <AppShell me={me}>{children}</AppShell>;
}
