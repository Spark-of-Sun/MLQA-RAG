/**
 * Server-side session store (doc 8.3, G8.5, DEF-58).
 *
 * The browser holds only an opaque, httpOnly, SameSite session ID; the tokens live here, encrypted
 * with AES-256-GCM under a key derived from the session secret, in Valkey with a TTL. Deleting the
 * Valkey entry ends access at once ("sign out everywhere", revocation). A per-user index lets the
 * back-channel logout and the identity service's revocation remove every session of a user.
 */
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import Redis from "ioredis";
import type { SessionData, SessionDataStore } from "@auth0/nextjs-auth0/types";

const ABSOLUTE_SECONDS = 8 * 3600; // privileged limit; tenants may be looser later (doc 8.4)

export function deriveKey(secret: string): Buffer {
  return createHash("sha256").update(`lmqa/session/v1|${secret}`).digest();
}

export function seal(key: Buffer, plaintext: string, aad: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(aad));
  const body = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}

export function open(key: Buffer, sealed: string, aad: string): string | null {
  try {
    const raw = Buffer.from(sealed, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", key, raw.subarray(0, 12));
    decipher.setAAD(Buffer.from(aad));
    decipher.setAuthTag(raw.subarray(12, 28));
    return Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString("utf8");
  } catch {
    return null; // wrong key, wrong session ID or tampering: the session simply does not exist
  }
}

export class ValkeySessionStore implements SessionDataStore {
  private readonly key: Buffer;

  constructor(
    private readonly redis: Redis,
    secret: string,
  ) {
    this.key = deriveKey(secret);
  }

  async get(id: string): Promise<SessionData | null> {
    const sealed = await this.redis.get(`sess:${id}`);
    if (!sealed) return null;
    const text = open(this.key, sealed, id); // bound to the ID: a copied value cannot be replayed under another ID
    return text ? (JSON.parse(text) as SessionData) : null;
  }

  async set(id: string, session: SessionData): Promise<void> {
    await this.redis.set(`sess:${id}`, seal(this.key, JSON.stringify(session), id), "EX", ABSOLUTE_SECONDS);
    const sub = (session.user as { sub?: string } | undefined)?.sub;
    if (sub) {
      await this.redis.sadd(`sub:${sub}`, id);
      await this.redis.expire(`sub:${sub}`, ABSOLUTE_SECONDS);
    }
  }

  async delete(id: string): Promise<void> {
    await this.redis.del(`sess:${id}`);
  }

  async deleteByLogoutToken({ sub }: { sub?: string; sid?: string }): Promise<void> {
    if (!sub) return;
    const ids = await this.redis.smembers(`sub:${sub}`);
    if (ids.length) await this.redis.del(...ids.map((i) => `sess:${i}`));
    await this.redis.del(`sub:${sub}`);
  }
}

let shared: Redis | undefined;
export function valkey(): Redis {
  shared ??= new Redis(process.env.VALKEY_URL ?? "redis://localhost:6379", {
    username: usable(process.env.VALKEY_USER_FRONTEND),
    password: usable(process.env.VALKEY_PASSWORD_FRONTEND),
    lazyConnect: false,
    maxRetriesPerRequest: 2,
  });
  return shared;
}

/** A value from .env.example that was never replaced counts as "not configured". */
export function usable(value: string | undefined): string | undefined {
  return value && !/^<.*>$/.test(value) ? value : undefined;
}
