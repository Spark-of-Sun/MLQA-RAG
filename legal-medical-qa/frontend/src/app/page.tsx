import { redirect } from "next/navigation";
import { homeFor } from "@/lib/capabilities";
import { loadIdentity } from "@/lib/gateway";

export const dynamic = "force-dynamic";

export default async function Home() {
  const who = await loadIdentity();
  if (who.kind === "anonymous") redirect("/auth/login");
  if (who.kind === "onboarding") redirect("/onboarding");
  redirect(homeFor(who.me));
}
