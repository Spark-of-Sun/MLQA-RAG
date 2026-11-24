import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ProfileForm } from "@/components/account/profile-form";
import { requireMe } from "@/lib/backend";
import { hasFeature } from "@/lib/features";

export const metadata: Metadata = { title: "Profile" };

export default async function ProfilePage() {
  const me = await requireMe();
  // Frozen MVP-only feature (DEV-21, pending Q-04): the page exists only while `profiles` is on, like its API.
  if (!hasFeature(me, "profiles")) notFound();
  return <ProfileForm role={me.membership?.role ?? "tenant"} />;
}
