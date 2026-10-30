import { Chat } from "@/components/Chat";
import { Shell } from "@/components/Shell";
import { requireMe } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  const me = await requireMe("/chat");
  return (
    <Shell me={me}>
      <Chat />
    </Shell>
  );
}
