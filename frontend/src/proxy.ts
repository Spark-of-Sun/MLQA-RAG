import { NextResponse, type NextRequest } from "next/server";

import { APP_BASE_URL, auth0 } from "@/lib/auth0";

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

// Next.js 16 proxy (replaces middleware.ts, blueprint 17.1): mounts the Auth0 routes (/auth/login, /auth/callback,
// /auth/logout), keeps the rolling session fresh, and sets a per-request nonce CSP (blueprint 17.3).
export async function proxy(request: NextRequest) {
  // One canonical local address. Auth0 always returns to APP_BASE_URL (localhost), and the login-state cookie is
  // bound to the host that started the login, so a login begun at 127.0.0.1 would fail with "state is invalid".
  const base = new URL(APP_BASE_URL);
  const host = request.headers.get("host") ?? "";
  const hostname = host.replace(/:\d+$/, "");
  if (host !== base.host && LOOPBACK.has(hostname) && LOOPBACK.has(base.hostname)) {
    // Not a 3xx: Next.js rewrites a same-port Location header to a relative path, which would keep the browser on
    // the wrong host. A refresh page moves it to the canonical origin.
    const target = new URL(request.nextUrl.pathname + request.nextUrl.search, base).toString();
    const href = target.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
    return new NextResponse(
      `<!doctype html><meta http-equiv="refresh" content="0;url=${href}"><a href="${href}">Continue to ${base.origin}</a>`,
      { status: 200, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
    );
  }

  const authResponse = await auth0.middleware(request);
  if (request.nextUrl.pathname.startsWith("/auth/")) {
    return authResponse;
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  const https = (process.env.APP_BASE_URL ?? "").startsWith("https://");
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(https ? ["upgrade-insecure-requests"] : []),
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  for (const cookie of authResponse.cookies.getAll()) {
    response.cookies.set(cookie);
  }
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
