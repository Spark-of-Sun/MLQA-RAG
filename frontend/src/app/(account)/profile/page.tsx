import type { Metadata } from "next";

import { ProfileForm } from "@/components/account/profile-form";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Profile" };

export default async function ProfilePage() {
  const me = await requireMe();
  return <ProfileForm role={me.membership?.role ?? "tenant"} />;
}
