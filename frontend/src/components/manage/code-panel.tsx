"use client";

import { Check, Copy, KeyRound, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, Button, Card, Modal } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDay } from "@/lib/format";
import type { CodeInfo, NewCode } from "@/lib/types";

// The plaintext code is shown once, copied with a button, and cleared from state when the dialog closes
// (blueprint 7.6, 17.3). Afterwards only the lookup ID, dates and uses are shown.
export function CodePanel({ kind }: { kind: "org" | "admin" }) {
  const path = kind === "org" ? "org/code" : "workspace/code";
  const [info, setInfo] = useState<CodeInfo | null | undefined>(undefined);
  const [fresh, setFresh] = useState<NewCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await api.get<CodeInfo | null>(path));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  async function rotate() {
    setBusy(true);
    setError(null);
    try {
      setFresh(await api.post<NewCode>(path));
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const title = kind === "org" ? "Organization Code" : "Member invite code";
  const who = kind === "org" ? "a new admin" : "a new member";
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-ink-100 p-2 text-ink-600">
          <KeyRound className="size-4" aria-hidden />
        </div>
        <div className="flex-1">
          <h2 className="font-semibold text-ink-950">{title}</h2>
          <p className="mt-0.5 text-sm text-ink-500">
            Share it with {who}. They sign in, enter it, and wait for your approval. A leaked code can only create a request
            you can reject.
          </p>
          {info && (
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-600">
              <div>
                <dt className="inline text-ink-400">Lookup ID </dt>
                <dd className="inline font-mono">{info.lookup_id}</dd>
              </div>
              <div>
                <dt className="inline text-ink-400">Expires </dt>
                <dd className="inline">{formatDay(info.expires_at)}</dd>
              </div>
              <div>
                <dt className="inline text-ink-400">Uses </dt>
                <dd className="inline">
                  {info.uses} of {info.max_uses}
                </dd>
              </div>
            </dl>
          )}
          {info === null && <p className="mt-3 text-xs text-ink-500">No active code yet.</p>}
          {error && (
            <div className="mt-3">
              <Alert>{error}</Alert>
            </div>
          )}
        </div>
        <Button variant={info ? "secondary" : "primary"} busy={busy} onClick={rotate}>
          <RefreshCw className="size-4" aria-hidden />
          {info ? "Rotate code" : "Generate code"}
        </Button>
      </div>
      {fresh && <CodeDialog code={fresh} kind={kind} onClose={() => setFresh(null)} />}
    </Card>
  );
}

function CodeDialog({ code, kind, onClose }: { code: NewCode; kind: "org" | "admin"; onClose: () => void }) {
  const [copied, setCopied] = useState<"code" | "link" | null>(null);
  const link = `${window.location.origin}/onboarding#join=${kind === "org" ? "admin" : "tenant"}&code=${code.code}`;
  async function copy(value: string, which: "code" | "link") {
    await navigator.clipboard.writeText(value);
    setCopied(which);
    setTimeout(() => setCopied(null), 2000);
  }
  return (
    <Modal title={kind === "org" ? "New Organization Code" : "New member invite code"} onClose={onClose}>
      <Alert tone="amber">This is the only time the code is shown. Copy it now. Any previous code no longer works.</Alert>
      <p className="mt-4 rounded-lg bg-inverse px-4 py-3 text-center font-mono text-sm leading-6 tracking-wider break-all text-on-inverse">
        {code.code}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => copy(code.code, "code")}>
          {copied === "code" ? <Check className="size-4" /> : <Copy className="size-4" />} Copy code
        </Button>
        <Button variant="secondary" onClick={() => copy(link, "link")}>
          {copied === "link" ? <Check className="size-4" /> : <Copy className="size-4" />} Copy invite link
        </Button>
      </div>
      <p className="mt-3 text-xs text-ink-500">
        The invite link carries the code after “#”, which browsers never send to a server. Valid until{" "}
        {formatDay(code.expires_at)} for up to {code.max_uses} uses.
      </p>
      <div className="mt-5 flex justify-end">
        <Button variant="secondary" onClick={onClose}>
          Done
        </Button>
      </div>
    </Modal>
  );
}
