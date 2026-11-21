import { redirect } from "next/navigation";
import { Onboarding } from "@/components/Onboarding";
import { homeFor } from "@/lib/capabilities";
import { identityOrLogin } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const who = await identityOrLogin("/onboarding");
  if (who.kind === "member" && who.me.state === "active" && who.me.org_state === "active") redirect(homeFor(who.me));
  const state = who.kind === "onboarding" ? (who.status.state ?? null) : who.me.state;
  return <Onboarding initialState={state} />;
}
