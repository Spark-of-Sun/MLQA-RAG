/**
 * Route protection, CSP nonce generation, and session gating.
 * Next.js 16 proxy implementation per Master System Design §17.1 & §17.3.
 */

import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "./lib/auth0";
import { canAccessRoute } from "./lib/capabilities";

export default async function proxy(req: NextRequest): Promise<NextResponse> {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const { pathname } = req.nextUrl;

  // Static assets and internal next paths pass through
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon.ico") ||
    pathname.startsWith("/static")
  ) {
    return NextResponse.next();
  }

  // Define Content Security Policy with unique request nonce
  const isDev = process.env.NODE_ENV !== "production";
  const scriptSrc = isDev
    ? `'self' 'unsafe-eval' 'nonce-${nonce}'`
    : `'self' 'strict-dynamic' 'nonce-${nonce}'`;

  const cspHeader = [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  // Session retrieval from opaque httpOnly cookie
  const sessionId = req.cookies.get("lmqa_session")?.value;
  const session = getSession(sessionId);

  // If unauthenticated and accessing protected routes, redirect to onboarding/login
  const isPublicRoute =
    pathname.startsWith("/onboarding") ||
    pathname.startsWith("/api/auth") ||
    pathname === "/";

  if (!session && !isPublicRoute) {
    const loginUrl = new URL("/onboarding", req.url);
    loginUrl.searchParams.set("returnTo", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Capability check for authenticated routes
  if (session && !canAccessRoute(session.principal.role, pathname)) {
    // Return 404 per §17.1 so existence of forbidden route is not revealed
    return new NextResponse("Not Found", { status: 404 });
  }

  // Set security headers on request and response
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", cspHeader);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });

  response.headers.set("Content-Security-Policy", cspHeader);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");

  // Onboarding enforces no-referrer per §17.3
  if (pathname.startsWith("/onboarding")) {
    response.headers.set("Referrer-Policy", "no-referrer");
  } else {
    response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  }

  return response;
}
