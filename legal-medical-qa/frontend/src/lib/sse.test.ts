import { describe, expect, it } from "vitest";
import { StreamDecoder, type StreamEvent } from "@/lib/sse";

const encoder = new TextEncoder();

// A realistic gated answer: multi-byte characters (section sign, accented, CJK) sit inside the data.
const WIRE = [
  'id: r1:1\nevent: status\ndata: {"stage":"retrieving","request_id":"r1"}\n\n',
  'id: r1:2\nevent: sentence\ndata: {"text":"Notice is 30 days under § 4.2 [chunk_1].","aliases":["chunk_1"],"citations":[],"index":0}\n\n',
  'id: r1:3\nevent: notice\ndata: {"text":"A claim in this answer could not be verified and was removed.","reason":"V5","kind":"stripped"}\n\n',
  'id: r1:4\nevent: sentence\ndata: {"text":"Résumé 条款 — done.","aliases":[],"citations":[],"index":1}\n\n',
  'id: r1:5\nevent: citations\ndata: {"citations":[]}\n\n',
  'id: r1:6\nevent: done\ndata: {"request_id":"r1"}\n\n',
].join("");

function decodeAll(chunks: Uint8Array[]): StreamEvent[] {
  const d = new StreamDecoder();
  const out: StreamEvent[] = [];
  for (const c of chunks) out.push(...d.push(c));
  out.push(...d.finish());
  return out;
}

describe("stream decoding (G8.4)", () => {
  const whole = encoder.encode(WIRE);
  const reference = decodeAll([whole]);

  it("parses the whole stream into typed events in order", () => {
    expect(reference.map((e) => e.type)).toEqual(["status", "sentence", "notice", "sentence", "citations", "done"]);
    const sentence = reference[1];
    expect(sentence?.type === "sentence" && sentence.text).toBe("Notice is 30 days under § 4.2 [chunk_1].");
    const second = reference[3];
    expect(second?.type === "sentence" && second.text).toBe("Résumé 条款 — done.");
  });

  it("renders identically when sliced at EVERY byte boundary", () => {
    for (let i = 1; i < whole.length; i++) {
      const events = decodeAll([whole.slice(0, i), whole.slice(i)]);
      expect(events, `split at byte ${i}`).toEqual(reference);
    }
  });

  it("renders identically one byte at a time", () => {
    const bytes = Array.from(whole, (b) => new Uint8Array([b]));
    expect(decodeAll(bytes)).toEqual(reference);
  });

  it("renders identically for three-way splits", () => {
    for (let i = 1; i < whole.length; i += 7) {
      for (let j = i + 1; j < whole.length; j += 11) {
        expect(decodeAll([whole.slice(0, i), whole.slice(i, j), whole.slice(j)])).toEqual(reference);
      }
    }
  });

  it("keeps the event id, which the client sends back as Last-Event-ID to resume", () => {
    expect(reference.map((e) => e.id)).toEqual(["r1:1", "r1:2", "r1:3", "r1:4", "r1:5", "r1:6"]);
  });

  it("drops an unknown or malformed event instead of crashing", () => {
    const bad = encoder.encode('event: surprise\ndata: {}\n\nevent: sentence\ndata: {not json\n\nevent: done\ndata: {}\n\n');
    expect(decodeAll([bad]).map((e) => e.type)).toEqual(["done"]);
  });

  it("the naive per-chunk newline split would have broken (why a buffered parser is mandatory)", () => {
    const naive = (chunks: Uint8Array[]) => {
      const td = new TextDecoder();
      let ok = 0;
      for (const c of chunks) {
        for (const line of td.decode(c).split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              JSON.parse(line.slice(6));
              ok++;
            } catch {
              /* a frame split across chunks: the naive client loses it */
            }
          }
        }
      }
      return ok;
    };
    const total = naive([whole]);
    const worst = Math.min(...Array.from({ length: whole.length - 1 }, (_, i) => naive([whole.slice(0, i + 1), whole.slice(i + 1)])));
    expect(worst).toBeLessThan(total);
  });
});
