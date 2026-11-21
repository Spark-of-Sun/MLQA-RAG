import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="text-sm font-medium text-ink-500">404</p>
      <h1 className="text-2xl font-semibold text-ink-950">Page not found</h1>
      <Link href="/home" className="text-sm font-medium text-link hover:underline">
        Go to your workspace
      </Link>
    </div>
  );
}
