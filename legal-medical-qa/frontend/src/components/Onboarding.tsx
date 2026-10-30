"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useInvite } from "@/lib/invite";
import { Notice } from "@/components/Shell";

type Flow = "organization" | "admin" | "tenant";
interface Status {
  member: boolean;
  state?: string;
  auth0_org_id?: string | null;
}

const UNIFORM = "That code is invalid or has expired.";

export function Onboarding({ initialState }: { initialState: string | null }) {
  const invite = useInvite(); // an invite link pre-selects the flow and fills the code
  const [chosen, setChosen] = useState<Flow | null>(null);
  const flow: Flow | null = chosen ?? invite?.kind ?? null;
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(
    initialState === "pending_approval" ? { tone: "info", text: "Your request is waiting for approval. You will get access as soon as it is approved." } : null,
  );
  const [typed, setTyped] = useState<string | null>(null);
  const code = typed ?? invite?.code ?? "";
  const setCode = (value: string) => setTyped(value);
  const [name, setName] = useState("");
  const [deployment, setDeployment] = useState("legal");
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } catch (error) {
      const isCode = error instanceof ApiError && error.status === 400;
      setMessage({ tone: "error", text: isCode ? UNIFORM : "Something went wrong. Please try again." });
    } finally {
      setBusy(false);
      setTyped("");
    }
  }

  async function enter() {
    const status = await api<Status>("/onboarding/status");
    if (status.member && status.auth0_org_id) {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- the Auth0 redirect needs a full-page navigation
      window.location.assign(`/api/session/start?mode=main&org=${encodeURIComponent(status.auth0_org_id)}&returnTo=/`);
    } else if (status.member && status.state === "active") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a full reload re-reads the session
      window.location.assign("/");
    } else {
      setMessage({ tone: "info", text: "Your request is waiting for approval." });
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-12">
      <h1 className="text-2xl font-semibold">Welcome. How will you use Onekami?</h1>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      <div className="grid gap-4 sm:grid-cols-3">
        {(
          [
            ["organization", "Create an organization", "You own it and approve its administrators."],
            ["admin", "Join as an administrator", "You have an Organization Code."],
            ["tenant", "Join as a team member", "You have an Admin Code from your administrator."],
          ] as const
        ).map(([id, title, hint]) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              setChosen(id);
              setPreview(null);
              setMessage(null);
            }}
            aria-pressed={flow === id}
            className={`rounded-lg border bg-white p-4 text-left shadow-sm hover:border-indigo-500 ${flow === id ? "border-indigo-600 ring-1 ring-indigo-600" : "border-slate-200"}`}
          >
            <span className="block font-medium">{title}</span>
            <span className="mt-1 block text-sm text-slate-600">{hint}</span>
          </button>
        ))}
      </div>

      {flow === "organization" && (
        <form
          className="space-y-3 rounded-lg bg-white p-4 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await api("/onboarding/organization", { method: "POST", json: { name, deployment_type: deployment } });
              await enter();
            });
          }}
        >
          <label className="block text-sm font-medium" htmlFor="org-name">Organization name</label>
          <input id="org-name" required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded border border-slate-300 px-3 py-2" />
          <label className="block text-sm font-medium" htmlFor="deployment">What do you work with?</label>
          <select id="deployment" value={deployment} onChange={(e) => setDeployment(e.target.value)} className="w-full rounded border border-slate-300 px-3 py-2">
            <option value="legal">Legal documents</option>
            <option value="medical">Medical documents</option>
            <option value="both">Both</option>
          </select>
          <button disabled={busy} className="rounded bg-indigo-700 px-4 py-2 text-white disabled:opacity-50">Create organization</button>
        </form>
      )}

      {(flow === "admin" || flow === "tenant") && (
        <form
          className="space-y-3 rounded-lg bg-white p-4 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              if (flow === "tenant" && preview === null) {
                const result = await api<{ workspace_label: string }>("/onboarding/join-tenant/preview", { method: "POST", json: { code } });
                setPreview(result.workspace_label);
                return;
              }
              await api(flow === "admin" ? "/onboarding/join-admin" : "/onboarding/join-tenant", { method: "POST", json: { code } });
              setPreview(null);
              setMessage({ tone: "info", text: "Request sent. You will get access once it is approved." });
            });
          }}
        >
          <label className="block text-sm font-medium" htmlFor="code">{flow === "admin" ? "Organization Code" : "Admin Code"}</label>
          <input id="code" autoComplete="off" spellCheck={false} required value={code} onChange={(e) => setCode(e.target.value)} className="w-full rounded border border-slate-300 px-3 py-2 font-mono" />
          {preview && <Notice>You are joining: {preview}. Confirm to send your request.</Notice>}
          <button disabled={busy} className="rounded bg-indigo-700 px-4 py-2 text-white disabled:opacity-50">
            {flow === "tenant" && preview === null ? "Check code" : "Send request"}
          </button>
        </form>
      )}
    </div>
  );
}
