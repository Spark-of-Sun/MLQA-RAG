import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { ChatList } from "@/components/chat/chat-list";
import { requireMe } from "@/lib/backend";

// The chat list stays mounted while you move between chats; only the thread on the right changes.
export default async function ChatLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  if (me.membership?.role === "super_admin") redirect("/manage-admins"); // no data-plane access (blueprint 5.3)
  return (
    <div className="flex h-full">
      <ChatList />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
