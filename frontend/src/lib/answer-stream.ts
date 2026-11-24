"use client";

// Thin SSE client for sentence-gated answers (blueprint 11.6, 17.3, D15): no Vercel AI SDK. Only verified
// sentences ever arrive; `stripped` events become a visible marker. On a dropped connection the client resumes
// with Last-Event-ID and receives only sentences that were released and audited (G7.11).
import { SseParser } from "@/lib/sse";

export interface StreamCitation {
  number: number;
  chunk_id: string;
  spans: [number, number][];
}

export type StreamItem =
  | { kind: "sentence"; seq: number; text: string; citations: StreamCitation[]; refusal: boolean }
  | { kind: "stripped"; seq: number };

export interface StreamHandlers {
  onMeta?: (meta: { query_id: string; request_id: string }) => void;
  onItem: (item: StreamItem) => void;
  onDone: (done: { outcome: string; citations: unknown[]; model?: string; latency_ms?: number }) => void;
  onError: (detail: string) => void;
}

export async function streamAnswer(question: string, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  let queryId: string | null = null;
  let lastId: string | null = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    const headers: Record<string, string> = { "content-type": "application/json", accept: "text/event-stream" };
    if (lastId && queryId) {
      headers["last-event-id"] = lastId;
      headers["x-query-id"] = queryId;
    }
    let response: Response;
    try {
      response = await fetch("/api/backend/queries/stream", {
        method: "POST", headers, body: JSON.stringify({ question }), signal,
      });
    } catch {
      if (signal?.aborted) return;
      continue;
    }
    if (!response.ok || !response.body) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      handlers.onError(body?.detail ?? `Request failed (${response.status}).`);
      return;
    }
    const reader = response.body.getReader();
    const parser = new SseParser();
    let finished = false;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        const events = done ? parser.end() : parser.feed(value);
        for (const ev of events) {
          if (ev.id) lastId = ev.id;
          const data = JSON.parse(ev.data) as Record<string, unknown>;
          if (ev.event === "meta") {
            queryId = String(data.query_id);
            handlers.onMeta?.(data as { query_id: string; request_id: string });
          } else if (ev.event === "sentence") {
            handlers.onItem({ kind: "sentence", seq: Number(data.seq), text: String(data.text),
              citations: data.citations as StreamCitation[], refusal: Boolean(data.refusal) });
          } else if (ev.event === "stripped") {
            handlers.onItem({ kind: "stripped", seq: Number(data.seq) });
          } else if (ev.event === "done") {
            finished = true;
            handlers.onDone(data as { outcome: string; citations: unknown[] });
          } else if (ev.event === "error") {
            finished = true;
            handlers.onError(String(data.detail ?? "The answer stopped."));
          }
        }
        if (done) break;
      }
    } catch {
      if (signal?.aborted) return;
    }
    if (finished) return;
    if (!queryId) break; // nothing was released yet: do not resubmit the question silently
  }
  handlers.onError("The connection was lost. Released sentences above are complete and verified.");
}
