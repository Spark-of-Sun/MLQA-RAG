"use client";

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert, Button, Card, PageHeader, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate, ROLE_LABEL } from "@/lib/format";
import type { Profile, Role } from "@/lib/types";

const FIELDS = [
  { key: "name", label: "Full name", placeholder: "Carol Diaz", required: true },
  { key: "job_title", label: "Job title", placeholder: "Associate, Litigation", required: false },
  { key: "department", label: "Department or team", placeholder: "Commercial disputes", required: false },
  { key: "phone", label: "Phone", placeholder: "+1 415 555 0100", required: false },
] as const;

type Key = (typeof FIELDS)[number]["key"];

const WHO_SEES: Record<Role, string> = {
  tenant: "Your workspace admin can see these details in Manage members.",
  admin: "Your Super Admin can see your name and email in Manage admins.",
  super_admin: "Only you can see these details.",
};

export function ProfileForm({ role }: { role: Role }) {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState<Record<Key, string>>({ name: "", job_title: "", department: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function fill(p: Profile) {
    setProfile(p);
    setForm({ name: p.name ?? "", job_title: p.job_title ?? "", department: p.department ?? "", phone: p.phone ?? "" });
  }

  useEffect(() => {
    api
      .get<Profile>("profile")
      .then(fill)
      .catch((e) => { setError(errorMessage(e)); });
  }, []);

  const dirty = profile !== null && FIELDS.some(({ key }) => (profile[key] ?? "") !== form[key].trim());

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const changes = Object.fromEntries(
        FIELDS.filter(({ key }) => (profile[key] ?? "") !== form[key].trim()).map(({ key }) => [key, form[key].trim()]),
      );
      fill(await api.patch<Profile>("profile", changes));
      setSaved(true);
      router.refresh(); // the sidebar shows the name
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <PageHeader title="Profile" subtitle={WHO_SEES[role]} />
      {profile === null ? (
        error ? (
          <Alert>{error}</Alert>
        ) : (
          <Spinner label="Loading…" />
        )
      ) : (
        <div className="space-y-6">
          <Card className="p-6">
            <form onSubmit={submit} className="space-y-4">
              <div>
                <p className="text-xs font-medium text-ink-600">Email</p>
                <p className="mt-1 text-sm text-ink-900">{profile.email ?? "—"}</p>
                <p className="mt-0.5 text-xs text-ink-500">Your sign-in email comes from your login provider and is changed there.</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {FIELDS.map(({ key, label, placeholder, required }) => (
                  <label key={key} className="block">
                    <span className="text-xs font-medium text-ink-600">
                      {label}
                      {!required && <span className="font-normal text-ink-400"> (optional)</span>}
                    </span>
                    <input
                      value={form[key]}
                      required={required}
                      minLength={required ? 2 : undefined}
                      maxLength={key === "phone" ? 40 : 120}
                      inputMode={key === "phone" ? "tel" : undefined}
                      autoComplete={key === "name" ? "name" : key === "phone" ? "tel" : key === "job_title" ? "organization-title" : "off"}
                      placeholder={placeholder}
                      onChange={(e) => {
                        setSaved(false);
                        setForm((f) => ({ ...f, [key]: e.target.value }));
                      }}
                      className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm text-ink-900 focus:border-brand-400 focus:ring-2 focus:ring-brand-100 focus:outline-none"
                    />
                  </label>
                ))}
              </div>
              {error && <Alert>{error}</Alert>}
              {saved && <Alert tone="green">Profile saved.</Alert>}
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-ink-500">
                  {profile.profile_updated_at ? `Last updated ${formatDate(profile.profile_updated_at)}` : "Not edited yet."}
                </p>
                <Button type="submit" busy={busy} disabled={!dirty}>
                  <Save className="size-4" aria-hidden /> Save changes
                </Button>
              </div>
            </form>
          </Card>
          <Card className="p-6">
            <h2 className="font-semibold text-ink-950">Membership</h2>
            <dl className="mt-3 grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
              <dt className="text-ink-500">Role</dt>
              <dd className="text-ink-900">{ROLE_LABEL[profile.role]}</dd>
              <dt className="text-ink-500">Organization</dt>
              <dd className="text-ink-900">{profile.organization}</dd>
              {profile.workspace && (
                <>
                  <dt className="text-ink-500">Workspace</dt>
                  <dd className="text-ink-900">{profile.workspace}</dd>
                </>
              )}
              <dt className="text-ink-500">Requested</dt>
              <dd className="text-ink-900">{formatDate(profile.joined_at)}</dd>
              <dt className="text-ink-500">Approved</dt>
              <dd className="text-ink-900">{formatDate(profile.approved_at)}</dd>
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}
