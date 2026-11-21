"use client";

import { useState, type ReactNode } from "react";

/**
 * A secret is rendered ONCE (doc 17.3): copy it, and it is cleared from state when the dialog closes.
 * It is never put in the URL, storage, a cookie or a log.
 */
export function SecretOnce({ label, secret, onClose }: { label: string; secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const groups = secret.match(/.{1,8}/g)?.join(" ") ?? secret;
  return (
    <div role="dialog" aria-modal="true" aria-label={label} className="fixed inset-0 z-10 grid place-items-center bg-slate-900/50 p-4">
      <div className="w-full max-w-2xl space-y-3 rounded-lg bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold">{label}</h2>
        <p className="text-sm text-slate-600">This is the only time it is shown. Copy it now and store it safely; only a hashed form is kept.</p>
        <code className="block break-all rounded bg-slate-100 p-3 font-mono text-sm" data-testid="secret">{groups}</code>
        <div className="flex gap-2">
          <button type="button" className="rounded bg-indigo-700 px-3 py-1.5 text-white" onClick={() => void navigator.clipboard.writeText(secret.replaceAll(" ", "")).then(() => setCopied(true))}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button type="button" className="rounded border border-slate-300 px-3 py-1.5" onClick={onClose}>Close and clear</button>
        </div>
      </div>
    </div>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-slate-500">
        <tr>{head.map((h) => <th key={h} scope="col" className="py-1">{h}</th>)}</tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}
