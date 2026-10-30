import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-md px-4 py-24 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-slate-600">It may not exist, or you may not have access to it.</p>
      <Link className="mt-6 inline-block text-indigo-700 underline" href="/">
        Go to the start page
      </Link>
    </main>
  );
}
