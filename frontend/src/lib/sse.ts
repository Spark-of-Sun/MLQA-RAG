/**
 * The chat stream client (doc 17.3, G8.4). Uses `eventsource-parser`, which buffers across network
 * chunks: a frame split anywhere (even in the middle of a multi-byte character) is reassembled. The
 * naive "split each chunk on newlines and JSON.parse" approach (DEF-36) breaks on exactly that.
 *
 * Event protocol (doc 11.6): status, sentence, notice, citations, error, done. Only released,
 * validated sentences ever arrive; there is no provisional or unverified text.
 */
import { createParser, type EventSourceMessage } from "eventsource-parser";

export interface Citation {
  alias: string;
  doc_title: string;
  doc_version: number;
  page_start: number;
  page_end: number;
  section_path: string;
  clause_no: string | null;
  span_start: number;
  span_end: number;
}

export type StreamEvent =
  | { type: "status"; id: string | undefined; stage: string; kept?: number; request_id?: string }
  | { type: "sentence"; id: string | undefined; text: string; aliases: string[]; citations: Citation[]; index: number }
  | { type: "notice"; id: string | undefined; text: string; reason: string; kind: "stripped" | "refusal" }
  | { type: "citations"; id: string | undefined; citations: Citation[] }
  | { type: "error"; id: string | undefined; code: string }
  | { type: "done"; id: string | undefined; request_id?: string };

const KNOWN = new Set(["status", "sentence", "notice", "citations", "error", "done"]);

/** Turn one parsed SSE message into a typed event; an unknown or malformed event is dropped. */
export function toEvent(message: EventSourceMessage): StreamEvent | null {
  const name = message.event ?? "message";
  if (!KNOWN.has(name)) return null;
  try {
    const data = JSON.parse(message.data) as Record<string, unknown>;
    return { type: name, id: message.id, ...data } as StreamEvent;
  } catch {
    return null;
  }
}

/** Feed byte chunks (any slicing) and receive the typed events they contain, in order. */
export class StreamDecoder {
  private readonly decoder = new TextDecoder("utf-8");
  private readonly events: StreamEvent[] = [];
  private readonly parser = createParser({
    onEvent: (message) => {
      const event = toEvent(message);
      if (event) this.events.push(event);
    },
  });

  push(chunk: Uint8Array): StreamEvent[] {
    this.parser.feed(this.decoder.decode(chunk, { stream: true }));
    return this.events.splice(0);
  }

  finish(): StreamEvent[] {
    this.parser.feed(this.decoder.decode());
    return this.events.splice(0);
  }
}

/** Read a streaming fetch response as typed events. */
export async function* readStream(response: Response): AsyncGenerator<StreamEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new StreamDecoder();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of decoder.push(value)) yield event;
    }
    for (const event of decoder.finish()) yield event;
  } finally {
    reader.releaseLock();
  }
}
