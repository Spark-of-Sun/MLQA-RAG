import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { SignInButton } from "@/components/sign-in-button";
import { APP_NAME, APP_TAGLINE } from "@/lib/site";

export default async function LoginPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (session) {
    redirect("/dashboard");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm border border-line">
        <div className="border-b border-line px-8 py-8">
          <p className="font-serif text-2xl text-ink">{APP_NAME}</p>
          <p className="mt-1 text-sm text-ink-soft">{APP_TAGLINE}</p>
        </div>

        <div className="px-8 py-8">
          <h1 className="text-sm font-medium text-ink">Sign in to continue</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Access is granted through your organization&apos;s identity provider.
          </p>
          <div className="mt-6">
            <SignInButton />
          </div>
        </div>

        <div className="border-t border-line px-8 py-5">
          <p className="text-xs text-ink-soft">
            By continuing, you agree to your organization&apos;s acceptable-use and
            data-handling policies.
          </p>
        </div>
      </div>
    </main>
  );
}
