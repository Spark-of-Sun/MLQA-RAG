/**
 * Server-only access to the Gateway (doc 4.2): attaches the caller's Auth0 access token, which never
 * leaves the server. Only code in route handlers and server components imports this file.
 */
import { headers } from "next/headers";
import { audienceOf, audiences, getAuth0 } from "@/lib/auth0";
import type { Me } from "@/lib/capabilities";

const API = () => process.env.API_BASE_URL ?? "http://localhost:8000";

export type Mode = "onboarding" | "main";

export class SessionMissing extends Error {}

export async function accessToken(): Promise<{ token: string; mode: Mode }> {
  try {
    const { token } = await getAuth0().getAccessToken();
    return { token, mode: audienceOf(token) === audiences.main ? "main" : "onboarding" };
  } catch {
    throw new SessionMissing("no valid session");
  }
}

export interface GatewayInit {
  method?: string;
  body?: BodyInit | null;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

/** Call the Gateway as the signed-in user. The Cloudflare client address is passed through, nothing else. */
export async function gateway(path: string, init: GatewayInit = {}): Promise<Response> {
  const { token } = await accessToken();
  const incoming = await headers();
  const out = new Headers(init.headers);
  out.set("Authorization", `Bearer ${token}`);
  const ip = incoming.get("cf-connecting-ip");
  if (ip) out.set("CF-Connecting-IP", ip);
  return fetch(`${API()}${path}`, {
    method: init.method ?? "GET",
    headers: out,
    body: init.body ?? null,
    signal: init.signal,
    cache: "no-store",
    // @ts-expect-error `duplex` is required to stream a request body in Node and is not in lib.dom
    duplex: "half",
  });
}

export interface OnboardingStatus {
  member: boolean;
  role?: string;
  state?: string;
  reason?: string | null;
  auth0_org_id?: string | null;
}

/** Who the caller is, from the DATABASE via the Gateway (never from the token's own claims). */
export async function loadIdentity(): Promise<
  | { kind: "anonymous" }
  | { kind: "onboarding"; status: OnboardingStatus }
  | { kind: "member"; me: Me }
> {
  let mode: Mode;
  try {
    mode = (await accessToken()).mode;
  } catch {
    return { kind: "anonymous" };
  }
  if (mode === "onboarding") {
    const response = await gateway("/v1/onboarding/status");
    return { kind: "onboarding", status: response.ok ? ((await response.json()) as OnboardingStatus) : { member: false } };
  }
  const response = await gateway("/v1/me");
  if (!response.ok) return { kind: "anonymous" };
  return { kind: "member", me: (await response.json()) as Me };
}
