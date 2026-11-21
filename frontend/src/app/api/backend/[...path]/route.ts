import { NextResponse, type NextRequest } from "next/server";

import { auth0 } from "@/lib/auth0";
import { API_URL } from "@/lib/backend";

// BFF proxy (blueprint 17.1): the browser calls /api/backend/<path>; this handler attaches the user's access token
// server-side and forwards to the gateway's /v1/<path>. The browser never sees a token.
const SEGMENT = /^[A-Za-z0-9_.~-]+$/;

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!path.length || path.some((s) => !SEGMENT.test(s) || s === "." || s === "..")) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  if (request.method !== "GET") {
    // CSRF: state-changing calls must come from our own pages.
    const origin = request.headers.get("origin");
    const host = request.headers.get("host");
    if (!origin || !host || new URL(origin).host !== host) {
      return NextResponse.json({ detail: "Cross-site request refused" }, { status: 403 });
    }
  }
  let token: string;
  try {
    token = (await auth0.getAccessToken()).token;
  } catch {
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  }

  const headers: Record<string, string> = { authorization: `Bearer ${token}` };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers["x-forwarded-for"] = forwardedFor;

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/v1/${path.join("/")}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "The API is not reachable." }, { status: 502 });
  }
  return new NextResponse(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
  });
}

export { forward as GET, forward as POST, forward as DELETE };
