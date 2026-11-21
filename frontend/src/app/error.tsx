"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <h1 className="text-xl font-semibold text-ink-950">Something went wrong</h1>
      <p className="max-w-md text-sm text-ink-600">{error.message || "The service is temporarily unavailable."}</p>
      <div className="flex gap-2">
        <button type="button" onClick={reset} className="rounded-lg bg-ink-900 px-4 py-2 text-sm font-medium text-white">
          Try again
        </button>
        <a href="/auth/logout" className="rounded-lg border border-ink-200 px-4 py-2 text-sm font-medium text-ink-700">
          Sign out
        </a>
      </div>
    </div>
  );
}
