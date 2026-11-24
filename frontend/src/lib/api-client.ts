"use client";

// The only code that calls the backend from the browser; it goes through the BFF at /api/backend (blueprint 17.3).
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "Please check the form and try again.";
  }
  return `Request failed (${status}).`;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "content-type": "application/json" };
  }
  const response = await fetch(`/api/backend/${path.replace(/^\//, "")}`, init);
  if (response.status === 401 && (response.headers.get("www-authenticate") ?? "").includes("insufficient_user_authentication")) {
    // RFC 9470 step-up: sign in again with a passkey, then come back to this page.
    const back = encodeURIComponent(window.location.pathname);
    window.location.href = `/auth/login?returnTo=${back}&max_age=0&acr_values=urn:lmqa:acr:passkey&scope=openid%20profile%20email%20step_up`;
    throw new ApiError(401, "This action needs a fresh passkey sign-in…");
  }
  if (response.status === 401) {
    window.location.href = `/auth/login?returnTo=${encodeURIComponent(window.location.pathname)}`;
    throw new ApiError(401, "Your session has ended. Signing you in again…");
  }
  if (!response.ok) {
    const parsed: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, detailOf(parsed, response.status));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body?: unknown) => call<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => call<T>("PATCH", path, body),
  del: <T = void>(path: string) => call<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => call<T>("POST", path, form),
};

/** Tell other components (the chat list) that chats were created, renamed or deleted. */
export const CHATS_CHANGED = "lmqa:chats-changed";
export function notifyChatsChanged() {
  window.dispatchEvent(new Event(CHATS_CHANGED));
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
