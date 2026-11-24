import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { ChatList } from "@/components/chat/chat-list";
import { requireMe } from "@/lib/backend";
import { hasFeature } from "@/lib/features";

// The chat list stays mounted while you move between chats; only the thread on the right changes. Chats are a
// frozen MVP-only feature (DEV-21, pending Q-04 and Q-39): while `chats` is off there is no list, only questions.
export default async function ChatLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  if (me.membership?.role === "super_admin") redirect("/manage-admins"); // no data-plane access (blueprint 5.3)
  return (
    <div className="flex h-full">
      {hasFeature(me, "chats") && <ChatList />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
