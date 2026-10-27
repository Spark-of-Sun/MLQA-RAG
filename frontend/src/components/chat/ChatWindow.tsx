"use client";

import * as React from "react";
import { Send, Sparkles, AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { consumeSSEStream, type CitationHighlight, type SentenceEvent, type StatusEvent } from "@/lib/sse";
import { Button } from "../ui/Button";
import { CitationPanel } from "./CitationPanel";

interface Message {
  id: string;
  sender: "user" | "assistant";
  text?: string;
  sentences?: SentenceEvent[];
  status?: string;
}

export function ChatWindow() {
  const [messages, setMessages] = React.useState<Message[]>([
    {
      id: "init",
      sender: "assistant",
      text: "Welcome to MLQA-RAG. Ask any question regarding your authorized contracts and legal agreements. All answers are verified against source document chunks.",
    },
  ]);
  const [input, setInput] = React.useState("");
  const [isLoading, setIsLoading] = React.useState(false);
  const [currentStatus, setCurrentStatus] = React.useState<StatusEvent | null>(null);
  const [activeCitation, setActiveCitation] = React.useState<CitationHighlight | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) {
      return;
    }

    const userMessage: Message = {
      id: crypto.randomUUID(),
      sender: "user",
      text: input,
    };

    const assistantMsgId = crypto.randomUUID();
    const assistantMessage: Message = {
      id: assistantMsgId,
      sender: "assistant",
      sentences: [],
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setIsLoading(true);
    setCurrentStatus(null);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: userMessage.text }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Chat request failed with status: ${response.status}`);
      }

      await consumeSSEStream(response.body, {
        onStatus: (status) => {
          setCurrentStatus(status);
        },
        onSentence: (sentence) => {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? {
                    ...msg,
                    sentences: [...(msg.sentences || []), sentence],
                  }
                : msg,
            ),
          );
        },
        onComplete: () => {
          setIsLoading(false);
          setCurrentStatus(null);
        },
        onError: (err) => {
          setIsLoading(false);
          setCurrentStatus(null);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? {
                    ...msg,
                    text: `Error processing query: ${err.message}`,
                  }
                : msg,
            ),
          );
        },
      });
    } catch (err) {
      setIsLoading(false);
      setCurrentStatus(null);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? {
                ...msg,
                text: `Connection failed: ${err instanceof Error ? err.message : String(err)}`,
              }
            : msg,
        ),
      );
    }
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      {/* Main Chat Stream */}
      <div className="flex flex-1 flex-col overflow-hidden bg-slate-50">
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-2xl rounded-lg p-4 ${
                  msg.sender === "user"
                    ? "bg-slate-900 text-white shadow-sm"
                    : "bg-white text-slate-900 border border-slate-200 shadow-sm"
                }`}
              >
                {msg.text ? (
                  <p className="text-sm leading-relaxed">{msg.text}</p>
                ) : null}

                {msg.sentences && msg.sentences.length > 0 ? (
                  <div className="space-y-2">
                    {msg.sentences.map((sent) => (
                      <div key={sent.ordinal} className="text-sm leading-relaxed inline">
                        {sent.verified ? (
                          <span className="text-slate-900">
                            {sent.text}{" "}
                            {sent.citations.map((cite, idx) => (
                              <button
                                key={idx}
                                onClick={() => setActiveCitation(cite)}
                                className="inline-flex items-center text-xs font-semibold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200 ml-1 transition-colors cursor-pointer"
                                title={`Inspect citation: ${cite.docTitle}`}
                              >
                                [{idx + 1}]
                              </button>
                            ))}
                          </span>
                        ) : (
                          <span className="text-rose-700 bg-rose-50 px-1 py-0.5 rounded border border-rose-200 inline-flex items-center gap-1">
                            <AlertCircle className="h-3 w-3 inline" />
                            [Could not be verified against corpus: proposition refused]
                          </span>
                        )}
                        {" "}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))}

          {/* Status Indicator Bar */}
          {isLoading && currentStatus ? (
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500 bg-white border border-slate-200 px-3 py-2 rounded-md max-w-sm">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-600" />
              <span>{currentStatus.message}</span>
            </div>
          ) : null}
        </div>

        {/* Input Bar */}
        <div className="border-t border-slate-200 bg-white p-4">
          <form onSubmit={handleSubmit} className="mx-auto flex max-w-3xl gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about authorized legal contracts (e.g. governing law, interest rates)..."
              disabled={isLoading}
              className="flex-1 rounded-md border border-slate-300 px-4 py-2 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900 disabled:opacity-50"
            />
            <Button type="submit" isLoading={isLoading} disabled={!input.trim()}>
              <Send className="h-4 w-4 mr-1" />
              <span>Ask</span>
            </Button>
          </form>
        </div>
      </div>

      {/* Side Provenance Panel */}
      <CitationPanel
        citation={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
    </div>
  );
}
