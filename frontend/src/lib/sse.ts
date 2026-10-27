/**
 * Robust buffered SSE client using eventsource-parser.
 * Resolves DEF-36: handles network chunks sliced at arbitrary byte boundaries.
 * Implements Master System Design §17.3.
 */

import { createParser, type EventSourceMessage } from "eventsource-parser";

export interface CitationHighlight {
  chunkId: string;
  docId: string;
  docTitle: string;
  sectionTitle?: string;
  pageRange?: string;
  confidenceScore: number;
  highlightSpan?: string;
}

export interface SentenceEvent {
  ordinal: number;
  text: string;
  verified: boolean;
  citations: CitationHighlight[];
}

export interface StatusEvent {
  stage: "retrieving" | "generating" | "validating" | "complete";
  message: string;
  elapsedMs: number;
}

export interface WarningEvent {
  code: string;
  message: string;
}

export interface SSECallbacks {
  onStatus?: (status: StatusEvent) => void;
  onSentence?: (sentence: SentenceEvent) => void;
  onWarning?: (warning: WarningEvent) => void;
  onComplete?: () => void;
  onError?: (err: Error) => void;
}

export async function consumeSSEStream(
  stream: ReadableStream<Uint8Array>,
  callbacks: SSECallbacks,
): Promise<void> {
  const decoder = new TextDecoder("utf-8");

  const parser = createParser({
    onEvent: (event: EventSourceMessage) => {
      try {
        if (event.event === "sentence") {
          const data: SentenceEvent = JSON.parse(event.data);
          callbacks.onSentence?.(data);
        } else if (event.event === "status") {
          const data: StatusEvent = JSON.parse(event.data);
          callbacks.onStatus?.(data);
        } else if (event.event === "warning") {
          const data: WarningEvent = JSON.parse(event.data);
          callbacks.onWarning?.(data);
        } else if (event.event === "done") {
          callbacks.onComplete?.();
        }
      } catch (err) {
        callbacks.onError?.(
          new Error(
            `Failed to parse SSE event data: ${err instanceof Error ? err.message : String(err)}`,
          ),
        );
      }
    },
    onError: (err) => {
      callbacks.onError?.(err);
    },
  });

  const reader = stream.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      parser.feed(decoder.decode(value, { stream: true }));
    }
    callbacks.onComplete?.();
  } catch (err) {
    callbacks.onError?.(
      err instanceof Error ? err : new Error(String(err)),
    );
  } finally {
    reader.releaseLock();
  }
}
