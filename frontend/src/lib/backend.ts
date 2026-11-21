// Server-only helpers: the BFF is the only code that holds tokens (blueprint 17.1).
import { redirect } from "next/navigation";
import { cache } from "react";

import { auth0 } from "@/lib/auth0";
import type { Me } from "@/lib/types";

export const API_URL = process.env.LMQA_API_INTERNAL_URL ?? "http://127.0.0.1:8000";

export class BackendUnavailable extends Error {}

async function accessToken(): Promise<string | null> {
  try {
    const { token } = await auth0.getAccessToken();
    return token;
  } catch {
    return null;
  }
}

/** The signed-in principal as resolved by the gateway, or a redirect to sign-in. Cached per request. */
export const requireMe = cache(async (): Promise<Me> => {
  const session = await auth0.getSession();
  if (!session) redirect("/auth/login");
  const token = await accessToken();
  if (!token) redirect("/auth/login");
  let response: Response;
  try {
    response = await fetch(`${API_URL}/v1/me`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    throw new BackendUnavailable("The API is not reachable. Is `make dev` running?");
  }
  if (response.status === 401) redirect("/auth/login");
  if (!response.ok) throw new BackendUnavailable(`The API returned ${response.status}.`);
  return (await response.json()) as Me;
});

/** Route a principal to its home screen (blueprint 17.1 routing table). */
export function homeFor(me: Me): string {
  const m = me.membership;
  if (!m || !m.active) return "/onboarding";
  return m.role === "super_admin" ? "/manage-admins" : "/chat";
}
