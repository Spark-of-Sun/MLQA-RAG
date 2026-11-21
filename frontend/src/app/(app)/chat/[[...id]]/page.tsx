import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Chat } from "@/components/chat/chat";
import { requireMe } from "@/lib/backend";

export const metadata: Metadata = { title: "Ask" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// /chat starts a new chat; /chat/<id> continues one. Whether the chat is yours is decided by the database (RLS).
export default async function ChatPage({ params }: { params: Promise<{ id?: string[] }> }) {
  const { id } = await params;
  if (id && (id.length !== 1 || !UUID.test(id[0] ?? ""))) notFound();
  const me = await requireMe();
  const conversationId = id?.[0] ?? null;
  return <Chat key={conversationId ?? "new"} conversationId={conversationId} kind={me.membership?.organization.kind ?? "both"} />;
}
