"use client";

import { Check, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { CHATS_CHANGED, api, errorMessage, notifyChatsChanged } from "@/lib/api-client";
import type { ChatSummary } from "@/lib/types";

function group(chats: ChatSummary[]): [string, ChatSummary[]][] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const day = 24 * 60 * 60 * 1000;
  const buckets: Record<string, ChatSummary[]> = { Today: [], Yesterday: [], "Previous 7 days": [], Older: [] };
  for (const c of chats) {
    const t = new Date(c.updated_at).getTime();
    const key =
      t >= startOfToday.getTime()
        ? "Today"
        : t >= startOfToday.getTime() - day
          ? "Yesterday"
          : t >= startOfToday.getTime() - 7 * day
            ? "Previous 7 days"
            : "Older";
    buckets[key]!.push(c);
  }
  return Object.entries(buckets).filter(([, items]) => items.length > 0);
}

export function ChatList() {
  const pathname = usePathname();
  const router = useRouter();
  const activeId = pathname.startsWith("/chat/") ? pathname.slice("/chat/".length) : null;
  const [chats, setChats] = useState<ChatSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setChats(await api.get<ChatSummary[]>("conversations?limit=100"));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const onChange = () => void load();
    window.addEventListener(CHATS_CHANGED, onChange);
    return () => window.removeEventListener(CHATS_CHANGED, onChange);
  }, [load]);

  async function rename(id: string) {
    const title = draft.trim();
    setEditing(null);
    if (!title) return;
    try {
      await api.patch(`conversations/${id}`, { title });
      notifyChatsChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function remove(id: string) {
    setConfirming(null);
    try {
      await api.del(`conversations/${id}`);
      if (id === activeId) router.push("/chat");
      notifyChatsChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-ink-200 bg-white/70 lg:flex" aria-label="Chats">
      <div className="p-3">
        <Link
          href="/chat"
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm font-medium text-ink-800 shadow-sm hover:bg-ink-50"
        >
          <Plus className="size-4" aria-hidden /> New chat
        </Link>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {error && <p className="px-2 py-1 text-xs text-rose-700">{error}</p>}
        {chats === null && !error && <p className="px-3 py-2 text-sm text-ink-400">Loading chats…</p>}
        {chats?.length === 0 && (
          <p className="px-3 py-2 text-sm text-ink-400">No chats yet. Your conversations are private to you.</p>
        )}
        {chats &&
          group(chats).map(([label, items]) => (
            <div key={label} className="mt-2">
              <p className="px-3 pb-1 text-[11px] font-semibold tracking-wide text-ink-400 uppercase">{label}</p>
              <ul>
                {items.map((c) => {
                  const active = c.id === activeId;
                  if (editing === c.id) {
                    return (
                      <li key={c.id} className="flex items-center gap-1 rounded-lg bg-white px-2 py-1 ring-1 ring-brand-300">
                        <input
                          autoFocus
                          value={draft}
                          maxLength={200}
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void rename(c.id);
                            if (e.key === "Escape") setEditing(null);
                          }}
                          aria-label="Chat title"
                          className="min-w-0 flex-1 bg-transparent px-1 py-1 text-sm outline-none"
                        />
                        <button type="button" onClick={() => rename(c.id)} className="rounded p-1 text-ink-500 hover:bg-ink-100" aria-label="Save title">
                          <Check className="size-3.5" />
                        </button>
                        <button type="button" onClick={() => setEditing(null)} className="rounded p-1 text-ink-500 hover:bg-ink-100" aria-label="Cancel">
                          <X className="size-3.5" />
                        </button>
                      </li>
                    );
                  }
                  return (
                    <li key={c.id} className="group relative">
                      <Link
                        href={`/chat/${c.id}`}
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-2 rounded-lg px-3 py-2 pr-16 text-sm ${
                          active ? "bg-brand-50 font-medium text-brand-800" : "text-ink-700 hover:bg-ink-100"
                        }`}
                      >
                        <MessageSquare className="size-3.5 shrink-0 opacity-60" aria-hidden />
                        <span className="truncate">{c.title}</span>
                      </Link>
                      <div
                        className={`absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-0.5 ${
                          confirming === c.id ? "" : "opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
                        }`}
                      >
                        {confirming === c.id ? (
                          <>
                            <button
                              type="button"
                              onClick={() => remove(c.id)}
                              className="rounded bg-rose-600 px-1.5 py-0.5 text-[11px] font-medium text-white"
                            >
                              Delete
                            </button>
                            <button type="button" onClick={() => setConfirming(null)} className="rounded p-1 text-ink-500 hover:bg-ink-200" aria-label="Keep chat">
                              <X className="size-3.5" />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => {
                                setEditing(c.id);
                                setDraft(c.title);
                              }}
                              className="rounded p-1 text-ink-500 hover:bg-ink-200"
                              aria-label={`Rename ${c.title}`}
                            >
                              <Pencil className="size-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirming(c.id)}
                              className="rounded p-1 text-ink-500 hover:bg-ink-200 hover:text-rose-700"
                              aria-label={`Delete ${c.title}`}
                            >
                              <Trash2 className="size-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
      </div>
      <p className="border-t border-ink-100 px-4 py-3 text-xs text-ink-400">
        Chats are visible only to you, not to your workspace admin.
      </p>
    </aside>
  );
}
