import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { Chat } from "@/components/chat/chat";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Ask" };

export default async function ChatPage() {
  const me = await requireMe();
  if (me.membership?.role === "super_admin") redirect("/manage-admins"); // no data-plane access (blueprint 5.3)
  return <Chat kind={me.membership?.organization.kind ?? "both"} />;
}
