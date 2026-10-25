import { NextRequest, NextResponse } from "next/server";
import { getSessionCookie } from "better-auth/cookies";

// Next.js 16 renamed "middleware" to "proxy" (same file-convention slot,
// same matcher config). This only checks that a session cookie EXISTS —
// it does not validate it. That's intentional and matches Better Auth's
// own guidance: keep the proxy fast (no DB call on every request) and do
// the real validation on the page itself. See app/dashboard/page.tsx and
// app/dashboard/dashboard.md for the actual check.
export async function proxy(request: NextRequest) {
  const sessionCookie = getSessionCookie(request);

  if (!sessionCookie) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*"],
};
