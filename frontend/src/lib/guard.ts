/**
 * Page guards for server components (doc 17.1). The role comes from the Gateway, not from anything the
 * browser holds, and a forbidden route is a 404 so its existence is not revealed.
 */
import { notFound, redirect } from "next/navigation";
import { accessFor, type Me } from "@/lib/capabilities";
import { loadIdentity } from "@/lib/gateway";

export type Guarded =
  | { kind: "member"; me: Me }
  | { kind: "onboarding"; status: { member: boolean; state?: string; auth0_org_id?: string | null } };

/** For the onboarding page: anonymous visitors log in, active members go home. */
export async function identityOrLogin(returnTo: string): Promise<Guarded> {
  const who = await loadIdentity();
  if (who.kind === "anonymous") redirect(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
  return who;
}

/** For app pages: returns the member, or redirects, or 404s. */
export async function requireMe(path: string): Promise<Me> {
  const who = await identityOrLogin(path);
  if (who.kind === "onboarding") {
    // A member whose organization is known re-authenticates against the main API (silent if Auth0 has a session).
    if (who.status.member && who.status.state === "active" && who.status.auth0_org_id) {
      redirect(`/api/session/start?mode=main&org=${encodeURIComponent(who.status.auth0_org_id)}&returnTo=${encodeURIComponent(path)}`);
    }
    redirect("/onboarding");
  }
  const decision = accessFor(who.me, path);
  if (decision.kind === "allow") return who.me;
  if (decision.kind === "redirect" && decision.to) redirect(decision.to);
  if (decision.kind === "blocked") redirect("/onboarding");
  notFound();
}
