// A text/event-stream parser that is correct at every byte boundary (blueprint 17.3, G8.4): bytes are decoded with
// a streaming TextDecoder (a multi-byte character split across reads is held back), lines may end in \n, \r\n or
// \r, a \r\n split across two reads is not taken for two line ends, and an event is dispatched only at its blank
// line. Comments (": keep-alive") are ignored. Pure functions, unit-tested with Vitest.

export interface SseEvent {
  id: string | null;
  event: string;
  data: string;
}

export class SseParser {
  private decoder = new TextDecoder("utf-8");
  private buffer = "";
  private pendingCr = false;
  private data: string[] = [];
  private event = "";
  private id: string | null = null;
  lastEventId: string | null = null;

  feed(chunk: Uint8Array): SseEvent[] {
    return this.text(this.decoder.decode(chunk, { stream: true }));
  }

  end(): SseEvent[] {
    const out = this.text(this.decoder.decode());
    return out;
  }

  private text(input: string): SseEvent[] {
    let s = input;
    if (this.pendingCr && s.startsWith("\n")) s = s.slice(1);
    this.pendingCr = false;
    this.buffer += s;
    const out: SseEvent[] = [];
    for (;;) {
      const m = /\r\n|\r|\n/.exec(this.buffer);
      if (!m) break;
      if (m[0] === "\r" && m.index === this.buffer.length - 1) {
        // a lone \r at the end may be the first half of \r\n: decide on the next read
        this.pendingCr = true;
      }
      const line = this.buffer.slice(0, m.index);
      this.buffer = this.buffer.slice(m.index + m[0].length);
      const ev = this.line(line);
      if (ev) out.push(ev);
    }
    return out;
  }

  private line(line: string): SseEvent | null {
    if (line === "") {
      if (this.data.length === 0 && !this.event) return null;
      const ev = { id: this.id, event: this.event || "message", data: this.data.join("\n") };
      if (this.id !== null) this.lastEventId = this.id;
      this.data = [];
      this.event = "";
      this.id = null;
      return ev;
    }
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.data.push(value);
    else if (field === "event") this.event = value;
    else if (field === "id" && !value.includes("\0")) this.id = value;
    return null;
  }
}
