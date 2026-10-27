/**
 * Server-side Auth0 session and token management for Next.js BFF.
 * Implements Master System Design §8 & §17.3 (No tokens in browser).
 */

import type { UserPrincipal } from "./capabilities";

export interface SessionData {
  sessionId: string;
  accessToken: string;
  idToken: string;
  expiresAt: number;
  principal: UserPrincipal;
}

// In-memory or server-side store for opaque session mapping
const sessionStore = new Map<string, SessionData>();

export function getSession(sessionId: string | undefined): SessionData | null {
  if (!sessionId) {
    return null;
  }
  const session = sessionStore.get(sessionId);
  if (!session) {
    return null;
  }
  if (Date.now() > session.expiresAt) {
    sessionStore.delete(sessionId);
    return null;
  }
  return session;
}

export function createSession(
  accessToken: string,
  idToken: string,
  principal: UserPrincipal,
  ttlSeconds: number = 3600,
): string {
  const sessionId = crypto.randomUUID();
  sessionStore.set(sessionId, {
    sessionId,
    accessToken,
    idToken,
    expiresAt: Date.now() + ttlSeconds * 1000,
    principal,
  });
  return sessionId;
}

export function revokeSession(sessionId: string): void {
  sessionStore.delete(sessionId);
}
