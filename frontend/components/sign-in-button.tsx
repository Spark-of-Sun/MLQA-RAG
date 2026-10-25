"use client";

import { useState } from "react";
import { authClient } from "@/lib/auth-client";

const providerId = process.env.NEXT_PUBLIC_OAUTH_PROVIDER_ID ?? "legalmed-oauth";
const label = process.env.NEXT_PUBLIC_OAUTH_PROVIDER_LABEL ?? "Continue with SSO";

export function SignInButton() {
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSignIn() {
    setError(null);
    setIsPending(true);
    try {
      // Generic OAuth providers use Better Auth's standard social sign-in
      // flow — this redirects to the provider, then back to
      // /api/auth/callback/<providerId>, then to callbackURL below.
      await authClient.signIn.social({
        provider: providerId,
        callbackURL: "/dashboard",
      });
    } catch {
      setError("Sign-in failed. Please try again.");
      setIsPending(false);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={handleSignIn}
        disabled={isPending}
        className="w-full bg-accent px-4 py-2.5 text-sm font-medium text-canvas transition-colors hover:bg-accent-ink disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isPending ? "Redirecting…" : label}
      </button>
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
    </div>
  );
}
