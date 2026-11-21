import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { requireMe } from "@/lib/backend";

// Account pages for every active role (blueprint 17.1 `(account)`).
export default async function AccountLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  if (!me.membership?.active) redirect("/onboarding");
  return <AppShell me={me}>{children}</AppShell>;
}
