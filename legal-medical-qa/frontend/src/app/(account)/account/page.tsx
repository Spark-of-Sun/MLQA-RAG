import { Shell } from "@/components/Shell";
import { requireMe } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function AccountPage() {
  const me = await requireMe("/account");
  return (
    <Shell me={me}>
      <h1 className="mb-4 text-xl font-semibold">Account</h1>
      <dl className="grid max-w-md grid-cols-2 gap-2 rounded-lg bg-white p-4 text-sm shadow-sm">
        <dt className="text-slate-500">Role</dt><dd>{me.role.replace("_", " ")}</dd>
        <dt className="text-slate-500">Status</dt><dd>{me.state.replace("_", " ")}</dd>
        <dt className="text-slate-500">Organization</dt><dd>{me.org_state}</dd>
      </dl>
      <p className="mt-4 max-w-md text-sm text-slate-600">
        Administrators sign in with a passkey or security key. Register a backup authenticator in your Auth0 profile so you can never be locked out.
      </p>
      <a className="mt-4 inline-block text-indigo-700 underline" href="/auth/logout">Sign out of this device</a>
    </Shell>
  );
}
