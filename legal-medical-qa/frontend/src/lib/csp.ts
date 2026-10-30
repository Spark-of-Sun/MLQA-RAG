/**
 * Content Security Policy with a per-request nonce (doc 17.3).
 *
 * `strict-dynamic` lets the nonce-bearing scripts load their own chunks; there is no `unsafe-inline`
 * for scripts and no `unsafe-eval` outside development. The browser talks only to this origin (every
 * Gateway call goes through the BFF), plus the object store origin for presigned uploads.
 */
export interface CspOptions {
  nonce: string;
  isDev: boolean;
  /** Origin of the object store that receives presigned PUT uploads, e.g. https://s3.us-east-1.amazonaws.com */
  uploadOrigin?: string;
}

export function buildCsp({ nonce, isDev, uploadOrigin }: CspOptions): string {
  const scripts = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(isDev ? ["'unsafe-eval'"] : [])];
  const connect = ["'self'", ...(uploadOrigin ? [uploadOrigin] : []), ...(isDev ? ["ws:"] : [])];
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": scripts,
    "style-src": ["'self'", `'nonce-${nonce}'`],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'"],
    "connect-src": connect,
    "frame-ancestors": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": ["'self'"],
    "object-src": ["'none'"],
  };
  const body = Object.entries(directives).map(([name, values]) => `${name} ${values.join(" ")}`);
  if (!isDev) body.push("upgrade-insecure-requests");
  return body.join("; ");
}

/** A fresh, unguessable nonce (16 random bytes, base64). Works in the Edge and Node runtimes. */
export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}
