/**
 * proxy.ts replaces middleware.ts in Next.js 16 (doc 17.1, 4.8). It does three things per request:
 * mounts the Auth0 routes (/auth/*), sets the nonce-based CSP, and gates unauthenticated visitors.
 * Role-level routing is done by the server layouts through `requireMe` (a Gateway call), because a
 * database round trip on every asset request would be wasteful.
 */
import { NextResponse, type NextRequest } from "next/server";
import { getAuth0 } from "@/lib/auth0";
import { buildCsp, newNonce } from "@/lib/csp";

const PUBLIC = [/^\/auth(\/|$)/, /^\/_next\//, /^\/favicon\.ico$/, /^\/api\/health$/];

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const auth = await getAuth0().middleware(request); // handles /auth/login, /auth/callback, /auth/logout, rolling sessions
  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/auth")) return auth;

  const nonce = newNonce();
  const uploadOrigin = process.env.OBJECT_STORE_PUBLIC_ORIGIN;
  const csp = buildCsp({ nonce, isDev: process.env.NODE_ENV !== "production", uploadOrigin });

  if (!PUBLIC.some((rule) => rule.test(pathname))) {
    const session = await getAuth0().getSession(request);
    if (!session && !pathname.startsWith("/api/")) {
      const login = new URL("/auth/login", request.url);
      login.searchParams.set("returnTo", pathname + request.nextUrl.search);
      return NextResponse.redirect(login);
    }
  }

  const forwarded = new Headers(request.headers);
  forwarded.set("x-nonce", nonce);
  forwarded.set("content-security-policy", csp);
  const response = NextResponse.next({ request: { headers: forwarded } });
  for (const cookie of auth.headers.getSetCookie()) response.headers.append("set-cookie", cookie);
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
