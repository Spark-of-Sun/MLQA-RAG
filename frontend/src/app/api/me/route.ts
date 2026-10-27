/**
 * BFF Principal and Capability resolution endpoint.
 * Returns verified session principal; frontend never decodes raw tokens.
 */

import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth0";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const sessionId = req.cookies.get("lmqa_session")?.value;
  const session = getSession(sessionId);

  if (!session) {
    // Fallback unauthenticated/demo context for initial bootstrap
    return NextResponse.json(
      {
        authenticated: false,
        principal: null,
      },
      { status: 401 },
    );
  }

  return NextResponse.json({
    authenticated: true,
    principal: session.principal,
  });
}
