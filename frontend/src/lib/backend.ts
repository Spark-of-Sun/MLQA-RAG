// Server-only helpers: the BFF is the only code that holds tokens (blueprint 17.1).
import { redirect } from "next/navigation";
import { cache } from "react";

import { auth0 } from "@/lib/auth0";
import type { Me } from "@/lib/types";

export const API_URL = process.env.LMQA_API_INTERNAL_URL ?? "http://127.0.0.1:8000";

/**
 * Headers for every server-side call to the gateway. On onekami.site the web app runs on Cloudflare Workers and
 * reaches the API through a Cloudflare Tunnel guarded by Cloudflare Access; CF_ACCESS_CLIENT_ID and
 * CF_ACCESS_CLIENT_SECRET are that Access service token (docs/deploy.md). Unset locally: nothing is added.
 */
export function apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const id = process.env.CF_ACCESS_CLIENT_ID;
  const secret = process.env.CF_ACCESS_CLIENT_SECRET;
  return id && secret ? { ...extra, "cf-access-client-id": id, "cf-access-client-secret": secret } : extra;
}

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
      headers: apiHeaders({ authorization: `Bearer ${token}` }),
      cache: "no-store",
    });
  } catch {
    throw new BackendUnavailable("The API is not reachable. Is `make dev` running?");
  }
  if (response.status === 401) redirect("/auth/login");
  if (!response.ok) throw new BackendUnavailable(`The API returned ${response.status}.`);
  return (await response.json()) as Me;
});

/**
 * Whether the public website and its docs (`(site)`) are on: the frozen `public_site` feature (DEV-21, pending Q-04).
 * Read from the public health check because visitors are not signed in. Fails closed: unreachable means off.
 */
export const publicSiteEnabled = cache(async (): Promise<boolean> => {
  try {
    const response = await fetch(`${API_URL}/v1/health`, { headers: apiHeaders(), cache: "no-store" });
    if (!response.ok) return false;
    const body = (await response.json()) as { public_site?: unknown };
    return body.public_site === true;
  } catch {
    return false;
  }
});

/** Route a principal to its home screen (blueprint 17.1 routing table). */
export function homeFor(me: Me): string {
  const m = me.membership;
  if (!m || !m.active) return "/onboarding";
  return m.role === "super_admin" ? "/manage-admins" : "/chat";
}

/**
 * The signed-in principal for pages anyone may open (the documentation): `null` when nobody is signed in, and
 * "unavailable" when the API cannot be reached. Never redirects. Role and status come from the gateway, as for
 * every other page, never from the token. Cached per request.
 */
export const findMe = cache(async (): Promise<Me | null | "unavailable"> => {
  const session = await auth0.getSession();
  if (!session) return null;
  const token = await accessToken();
  if (!token) return null;
  try {
    const response = await fetch(`${API_URL}/v1/me`, {
      headers: apiHeaders({ authorization: `Bearer ${token}` }),
      cache: "no-store",
    });
    if (response.status === 401) return null;
    if (!response.ok) return "unavailable";
    return (await response.json()) as Me;
  } catch {
    return "unavailable";
  }
});
