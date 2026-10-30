/**
 * The BFF proxy: the only way the browser reaches the Gateway (doc 4.8, 17.3).
 *
 * - Adds the caller's access token on the server; the browser never sees a token (G8.5).
 * - State-changing requests must be same-origin AND carry the custom header (CSRF defence in depth
 *   on top of SameSite cookies).
 * - A step-up challenge from the Gateway (RFC 9470) becomes a small JSON the UI uses to re-authenticate.
 * - Streams the response body unbuffered, which is what makes the SSE answer arrive sentence by sentence.
 */
import { NextResponse, type NextRequest } from "next/server";
import { gateway, SessionMissing } from "@/lib/gateway";

const FORWARD_REQUEST = new Set(["content-type", "accept", "idempotency-key", "last-event-id"]);
const FORWARD_RESPONSE = new Set(["content-type", "cache-control", "idempotent-replay", "www-authenticate"]);
const SAFE = new Set(["GET", "HEAD"]);

function sameOrigin(request: NextRequest): boolean {
  const base = process.env.APP_BASE_URL;
  const origin = request.headers.get("origin");
  return !!base && !!origin && new URL(base).origin === origin && request.headers.get("x-lmqa-csrf") === "1";
}

async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  if (!SAFE.has(request.method) && !sameOrigin(request)) {
    return NextResponse.json({ title: "Forbidden" }, { status: 403 });
  }
  const { path } = await context.params;
  const headers: Record<string, string> = {};
  for (const [key, value] of request.headers) if (FORWARD_REQUEST.has(key)) headers[key] = value;
  let upstream: Response;
  try {
    upstream = await gateway(`/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body: SAFE.has(request.method) ? null : request.body,
      signal: request.signal,
    });
  } catch (error) {
    if (error instanceof SessionMissing) return NextResponse.json({ title: "Unauthorized" }, { status: 401 });
    return NextResponse.json({ title: "Gateway unavailable" }, { status: 502 });
  }
  const challenge = upstream.headers.get("www-authenticate") ?? "";
  if (upstream.status === 401 && challenge.includes("insufficient_user_authentication")) {
    return NextResponse.json({ title: "Step-up required", stepUp: true }, { status: 401 });
  }
  const out = new Headers();
  for (const [key, value] of upstream.headers) if (FORWARD_RESPONSE.has(key)) out.set(key, value);
  out.set("Cache-Control", "no-store, no-transform");
  out.set("X-Accel-Buffering", "no");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const dynamic = "force-dynamic";
