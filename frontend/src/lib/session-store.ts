// Server-side session store in Valkey (blueprint 8.3, 17.3, D30, G8.5). The browser holds only an opaque,
// httpOnly session ID; tokens live here. Deleting the key ends access at once (logout, suspension). The BFF uses
// its own Valkey ACL user `frontend`, limited to `sess:*` keys. Enabled with FEATURE_SERVER_SIDE_SESSIONS=on.
import type { SessionData, SessionDataStore } from "@auth0/nextjs-auth0/types";
import Valkey from "iovalkey";

const PREFIX = "sess:";

export class ValkeySessionStore implements SessionDataStore {
  private client: Valkey;

  constructor(url: string, password: string) {
    this.client = new Valkey(url, { username: "frontend", password, lazyConnect: false, maxRetriesPerRequest: 2 });
  }

  async get(id: string): Promise<SessionData | null> {
    const raw = await this.client.get(PREFIX + id);
    return raw ? (JSON.parse(raw) as SessionData) : null;
  }

  async set(id: string, session: SessionData): Promise<void> {
    const expires = session.internal?.createdAt
      ? Math.max(60, session.internal.createdAt + 8 * 3600 - Math.floor(Date.now() / 1000))
      : 8 * 3600;
    await this.client.set(PREFIX + id, JSON.stringify(session), "EX", expires);
  }

  async delete(id: string): Promise<void> {
    await this.client.del(PREFIX + id);
  }
}

export function sessionStoreFromEnv(): ValkeySessionStore | undefined {
  if ((process.env.FEATURE_SERVER_SIDE_SESSIONS ?? "").toLowerCase() !== "on") return undefined;
  const url = process.env.VALKEY_URL;
  const password = process.env.VALKEY_USER_FRONTEND;
  if (!url || !password) throw new Error("server-side sessions need VALKEY_URL and VALKEY_USER_FRONTEND");
  return new ValkeySessionStore(url, password);
}
