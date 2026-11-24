import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Chat } from "@/components/chat/chat";
import { StreamingChat } from "@/components/chat/streaming-chat";
import { requireMe } from "@/lib/backend";
import { hasFeature } from "@/lib/features";

export const metadata: Metadata = { title: "Ask" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// /chat starts a new chat; /chat/<id> continues one. Whether the chat is yours is decided by the database (RLS).
// While the frozen `chats` feature is off (DEV-21) /chat asks single questions and /chat/<id> does not exist.
export default async function ChatPage({ params }: { params: Promise<{ id?: string[] }> }) {
  const { id } = await params;
  if (id && (id.length !== 1 || !UUID.test(id[0] ?? ""))) notFound();
  const me = await requireMe();
  const chats = hasFeature(me, "chats");
  const conversationId = id?.[0] ?? null;
  if (conversationId && !chats) notFound();
  // Sentence-gated streaming replaces the buffered chat once its gates pass (contracts/features.toml).
  if (!conversationId && hasFeature(me, "sentence_streaming")) return <StreamingChat />;
  return (
    <Chat
      key={conversationId ?? "new"}
      conversationId={conversationId}
      chats={chats}
      kind={me.membership?.organization.kind ?? "both"}
    />
  );
}
