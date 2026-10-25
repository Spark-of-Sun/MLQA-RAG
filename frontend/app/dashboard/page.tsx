import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { SignOutButton } from "@/components/sign-out-button";
import { APP_NAME } from "@/lib/site";

const NAV_ITEMS = [
  { label: "Overview", href: "/dashboard", active: true },
  { label: "Ask", href: "#", active: false },
  { label: "Library", href: "#", active: false },
  { label: "Audit", href: "#", active: false },
  { label: "Admin", href: "#", active: false },
] as const;

export default async function DashboardPage() {
  // Re-checked here even though proxy.ts already gated this route: the
  // proxy only confirms a session COOKIE exists, not that it's valid.
  // Defense in depth, the same pattern the backend repeats at every
  // service boundary (see services/retrieval/app/filters/access_filter.py).
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/login");
  }

  const firstName = session.user.name?.split(" ")[0];

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col justify-between border-r border-line px-6 py-8">
        <div>
          <p className="font-serif text-lg text-ink">{APP_NAME}</p>
          <nav className="mt-10 flex flex-col gap-1">
            {NAV_ITEMS.map((item) => (
              <a
                key={item.label}
                href={item.href}
                aria-current={item.active ? "page" : undefined}
                className={
                  item.active
                    ? "border-l-2 border-accent px-3 py-1.5 text-sm font-medium text-ink"
                    : "border-l-2 border-transparent px-3 py-1.5 text-sm text-ink-soft transition-colors hover:text-ink"
                }
              >
                {item.label}
              </a>
            ))}
          </nav>
        </div>

        <div className="border-t border-line pt-4">
          <p className="truncate text-sm text-ink">{session.user.name || session.user.email}</p>
          <div className="mt-2">
            <SignOutButton />
          </div>
        </div>
      </aside>

      <main className="flex-1 px-10 py-10">
        <h1 className="font-serif text-2xl text-ink">
          Welcome back{firstName ? `, ${firstName}` : ""}
        </h1>
        <p className="mt-1 text-sm text-ink-soft">
          This is a placeholder home. Ask, Library, and Audit views are coming next.
        </p>

        <div className="mt-10 border border-dashed border-line px-8 py-16 text-center">
          <p className="text-sm text-ink-soft">Nothing to show here yet.</p>
        </div>
      </main>
    </div>
  );
}
