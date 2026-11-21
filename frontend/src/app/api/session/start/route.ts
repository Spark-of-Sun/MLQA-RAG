/**
 * Starts an interactive login against a specific API (doc 7.1 step 4, 8.7):
 *   mode=main&org=<auth0 org id>  main API, organization required (after membership exists)
 *   mode=onboarding               onboarding API, no organization
 *   stepup=1                      a fresh, strong authentication (max_age=300)
 * The return path is restricted to same-site relative paths (no open redirect).
 */
import type { NextRequest } from "next/server";
import { audiences, getAuth0 } from "@/lib/auth0";

export const dynamic = "force-dynamic";

function safeReturn(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") ? value : "/";
}

export async function GET(request: NextRequest): Promise<Response> {
  const q = request.nextUrl.searchParams;
  const onboarding = q.get("mode") === "onboarding";
  const params: Record<string, string> = { audience: onboarding ? audiences.onboarding : audiences.main };
  // A step-up re-authentication has no org in the URL: it comes from the signed-in session.
  const sessionOrg = (await getAuth0().getSession(request))?.user?.org_id;
  const org = q.get("org") ?? (typeof sessionOrg === "string" ? sessionOrg : null);
  if (!onboarding && org && /^org_[A-Za-z0-9]+$/.test(org)) params.organization = org;
  if (q.get("stepup") === "1") params.max_age = "300";
  return getAuth0().startInteractiveLogin({ authorizationParameters: params, returnTo: safeReturn(q.get("returnTo")) }, request);
}
