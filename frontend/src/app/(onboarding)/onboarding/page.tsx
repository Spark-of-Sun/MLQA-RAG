import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { Onboarding } from "@/components/onboarding/onboarding";
import { homeFor, requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Get started", referrer: "no-referrer" };

export default async function OnboardingPage() {
  const me = await requireMe();
  if (me.membership?.active) redirect(homeFor(me));
  return <Onboarding me={me} />;
}
