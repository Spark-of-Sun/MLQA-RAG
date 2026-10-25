"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/auth-client";

export function SignOutButton() {
  const router = useRouter();
  const [isPending, setIsPending] = useState(false);

  async function handleSignOut() {
    setIsPending(true);
    await authClient.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <button
      type="button"
      onClick={handleSignOut}
      disabled={isPending}
      className="text-sm text-ink-soft transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-60"
    >
      {isPending ? "Signing out…" : "Sign out"}
    </button>
  );
}
