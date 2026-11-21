/**
 * The only module browser code uses to reach the platform (doc 4.7, 17.3). Every call goes to this
 * origin's BFF (`/api/v1/...`), which attaches the token on the server. Nothing here can see a token.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
  ) {
    super(`${status} ${title}`);
  }
}

/** The Gateway asked for a fresh, strong authentication (RFC 9470); the page is sent to re-authenticate. */
function stepUp(): never {
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- the Auth0 redirect needs a full-page navigation
  window.location.assign(`/api/session/start?mode=main&stepup=1&returnTo=${encodeURIComponent(window.location.pathname)}`);
  throw new ApiError(401, "Step-up required");
}

export async function api<T>(path: string, init: { method?: string; json?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { "x-lmqa-csrf": "1", accept: "application/json" };
  if (init.json !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") headers["idempotency-key"] = crypto.randomUUID();
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body: init.json === undefined ? null : JSON.stringify(init.json),
    credentials: "same-origin",
  });
  if (response.status === 401) {
    const body = (await response.json().catch(() => ({}))) as { stepUp?: boolean };
    if (body.stepUp) stepUp();
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- /auth/* is served by the Auth0 SDK, not a page
    window.location.assign("/auth/login");
    throw new ApiError(401, "Unauthorized");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  if (!response.ok) throw new ApiError(response.status, String(data.title ?? response.statusText));
  return data as T;
}

/** Start a streamed answer. The caller reads it with `readStream` from lib/sse. */
export function ask(question: string, signal: AbortSignal, lastEventId?: string): Promise<Response> {
  const headers: Record<string, string> = { "x-lmqa-csrf": "1", "content-type": "application/json", accept: "text/event-stream" };
  if (lastEventId) headers["last-event-id"] = lastEventId;
  return fetch("/api/v1/query", { method: "POST", headers, body: JSON.stringify({ question }), signal, credentials: "same-origin" });
}

/** Upload a file with the two-step presigned flow (doc 11.1): init, PUT to the quarantine URL, complete. */
export async function uploadDocument(
  file: File,
  meta: { visibility: "private" | "matter"; matter_id?: string; tier: number },
): Promise<{ id: string }> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const sha256_hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  const declared_type = (file.name.split(".").pop() ?? "").toLowerCase();
  const body = { title: file.name, declared_type, sha256_hex, ...meta };
  const started = await api<{ id: string; upload_url: string; required_headers: Record<string, string> }>("/documents/uploads", {
    method: "POST",
    json: body,
  });
  const put = await fetch(started.upload_url, { method: "PUT", headers: started.required_headers, body: file });
  if (!put.ok) throw new ApiError(put.status, "Upload to storage failed");
  await api(`/documents/${started.id}/complete`, { method: "POST", json: body });
  return { id: started.id };
}
