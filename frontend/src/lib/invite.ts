"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * An invite link carries its code in the URL FRAGMENT (`#code=...&kind=admin`), which browsers never send
 * to a server (doc 7.6). The fragment is read once, then removed from the address bar and history so it
 * cannot be shared by accident, and it is never put in a request URL; it is posted in a request body.
 */
export interface Invite {
  code: string;
  kind: "admin" | "tenant";
}

let captured: Invite | null | undefined;

function capture(): Invite | null {
  if (captured === undefined) {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const code = fragment.get("code");
    captured = code ? { code, kind: fragment.get("kind") === "admin" ? "admin" : "tenant" } : null;
  }
  return captured;
}

export function useInvite(): Invite | null {
  const invite = useSyncExternalStore(
    () => () => undefined,
    capture,
    () => null, // the server never sees a fragment
  );
  useEffect(() => {
    if (invite) window.history.replaceState(null, "", window.location.pathname);
  }, [invite]);
  return invite;
}
