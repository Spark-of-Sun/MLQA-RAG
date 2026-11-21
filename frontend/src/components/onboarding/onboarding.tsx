"use client";

import { ArrowLeft, Building2, Clock, KeyRound, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Logo } from "@/components/logo";
import { ThemeSwitch } from "@/components/theme-switch";
import { Alert, Button, Card } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { codeProblem, formatCode, normalizeCode } from "@/lib/codes";
import type { Me } from "@/lib/types";

type Flow = "choose" | "create" | "admin" | "tenant";

// Blueprint 7.1: the card only selects a flow; the role comes from the kind of code submitted, checked server-side.
export function Onboarding({ me }: { me: Me }) {
  const [flow, setFlow] = useState<Flow>("choose");
  const [prefill, setPrefill] = useState("");

  useEffect(() => {
    // Invite links carry the code in the URL fragment, which is never sent to a server (blueprint 7.6).
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const join = hash.get("join");
    const code = hash.get("code");
    if (code && (join === "admin" || join === "tenant")) {
      setFlow(join);
      setPrefill(code);
    }
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
  }, []);

  return (
    <div className="atmosphere-grid min-h-full bg-page">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <Link href="/" title="Home page">
          <Logo />
        </Link>
        <div className="flex items-center gap-4 text-sm text-ink-500">
          <span className="hidden sm:inline">{me.user.email}</span>
          <a href="/auth/logout" className="font-medium text-ink-700 hover:underline">
            Sign out
          </a>
          <ThemeSwitch />
        </div>
      </header>
      <div className="mx-auto max-w-3xl px-6 pt-10 pb-16">
        {me.membership ? (
          <Pending me={me} />
        ) : flow === "choose" ? (
          <Choose onPick={setFlow} />
        ) : (
          <div>
            <button
              type="button"
              onClick={() => setFlow("choose")}
              className="mb-4 inline-flex items-center gap-1 text-sm text-ink-500 hover:text-ink-800"
            >
              <ArrowLeft className="size-4" aria-hidden /> Back
            </button>
            {flow === "create" && <CreateOrg />}
            {flow === "admin" && <JoinAdmin prefill={prefill} />}
            {flow === "tenant" && <JoinTenant prefill={prefill} />}
          </div>
        )}
      </div>
    </div>
  );
}

function Choose({ onPick }: { onPick: (f: Flow) => void }) {
  const cards = [
    {
      flow: "create" as const,
      icon: Building2,
      title: "Create an organization",
      body: "For a law firm, hospital or practice. You become its Super Admin and invite the admins who run workspaces.",
    },
    {
      flow: "admin" as const,
      icon: KeyRound,
      title: "Join as an admin",
      body: "You have a 64-character Organization Code. You will run your own workspace once approved.",
    },
    {
      flow: "tenant" as const,
      icon: UserPlus,
      title: "Join a workspace",
      body: "You have a 32-character invite code from a workspace admin.",
    },
  ];
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight text-ink-950">Welcome. How will you use it?</h1>
      <p className="mt-2 text-ink-500">Choose one. You can only belong to one organization at a time.</p>
      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        {cards.map(({ flow, icon: Icon, title, body }) => (
          <button
            key={flow}
            type="button"
            onClick={() => onPick(flow)}
            className="rounded-2xl border border-ink-200 p-5 text-left shadow-sm transition hover:border-brand-300 hover:shadow-md"
          >
            <Icon className="size-5 text-link" aria-hidden />
            <p className="mt-3 font-semibold text-ink-900">{title}</p>
            <p className="mt-1 text-sm text-ink-500">{body}</p>
          </button>
        ))}
      </div>
    </>
  );
}

function useFinish() {
  const router = useRouter();
  return () => {
    router.push("/home");
    router.refresh();
  };
}

function CreateOrg() {
  const finish = useFinish();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"legal" | "medical" | "both">("legal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post("onboarding/organization", { name, kind });
      finish();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }
  return (
    <Card className="p-6">
      <h1 className="text-xl font-semibold text-ink-950">Create your organization</h1>
      <p className="mt-1 text-sm text-ink-500">
        As Super Admin you govern admins and see usage totals. You do not read workspace documents; admins and their
        members do.
      </p>
      <form
        className="mt-6 space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div>
          <label htmlFor="org-name" className="text-sm font-medium text-ink-800">
            Organization name
          </label>
          <input
            id="org-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            required
            placeholder="Hale & Partners LLP"
            className="mt-1.5 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm outline-none focus:border-brand-400"
          />
        </div>
        <fieldset>
          <legend className="text-sm font-medium text-ink-800">Type</legend>
          <div className="mt-1.5 grid grid-cols-3 gap-2">
            {(["legal", "medical", "both"] as const).map((k) => (
              <label
                key={k}
                className={`cursor-pointer rounded-lg border px-3 py-2 text-center text-sm font-medium capitalize ${
                  kind === k ? "border-brand-400 bg-brand-50 text-brand-700" : "border-ink-200 text-ink-600 hover:bg-surface-hover"
                }`}
              >
                <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} className="sr-only" />
                {k}
              </label>
            ))}
          </div>
        </fieldset>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" busy={busy} disabled={name.trim().length < 2}>
          Create organization
        </Button>
      </form>
    </Card>
  );
}

function CodeInput({ length, value, onChange }: { length: 32 | 64; value: string; onChange: (v: string) => void }) {
  const problem = codeProblem(value, length);
  return (
    <div>
      <label htmlFor="code" className="text-sm font-medium text-ink-800">
        {length === 64 ? "Organization Code" : "Invite code"} ({length} characters)
      </label>
      <textarea
        id="code"
        value={formatCode(value)}
        onChange={(e) => onChange(normalizeCode(e.target.value))}
        rows={length === 64 ? 2 : 1}
        spellCheck={false}
        autoComplete="off"
        placeholder={length === 64 ? "XXXXXXXX-XXXXXXXX-…" : "XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX"}
        className="mt-1.5 w-full resize-none rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm tracking-wider uppercase outline-none focus:border-brand-400"
      />
      {problem && <p className="mt-1 text-xs text-amber-700">{problem}</p>}
    </div>
  );
}

function JoinAdmin({ prefill }: { prefill: string }) {
  const finish = useFinish();
  const [code, setCode] = useState(normalizeCode(prefill));
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post("onboarding/join-admin", { code, workspace_name: workspace });
      finish();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }
  return (
    <Card className="p-6">
      <h1 className="text-xl font-semibold text-ink-950">Join as an admin</h1>
      <p className="mt-1 text-sm text-ink-500">
        Your request goes to the organization&apos;s Super Admin. Your workspace opens once they approve it.
      </p>
      <form
        className="mt-6 space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <CodeInput length={64} value={code} onChange={setCode} />
        <div>
          <label htmlFor="ws-name" className="text-sm font-medium text-ink-800">
            Name your workspace
          </label>
          <input
            id="ws-name"
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            maxLength={120}
            placeholder="Litigation, Cardiology, …"
            className="mt-1.5 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm outline-none focus:border-brand-400"
          />
        </div>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" busy={busy} disabled={codeProblem(code, 64) !== null || !code || workspace.trim().length < 2}>
          Send request
        </Button>
      </form>
    </Card>
  );
}

function JoinTenant({ prefill }: { prefill: string }) {
  const finish = useFinish();
  const [code, setCode] = useState(normalizeCode(prefill));
  const [preview, setPreview] = useState<{ organization: string; workspace: string; admin: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function check() {
    setBusy(true);
    setError(null);
    try {
      setPreview(await api.post("onboarding/preview-tenant", { code }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function join() {
    setBusy(true);
    setError(null);
    try {
      await api.post("onboarding/join-tenant", { code });
      finish();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }
  return (
    <Card className="p-6">
      <h1 className="text-xl font-semibold text-ink-950">Join a workspace</h1>
      <p className="mt-1 text-sm text-ink-500">The workspace admin approves your request before you get access.</p>
      {preview ? (
        <div className="mt-6 space-y-4">
          <div className="rounded-xl border border-ink-200 bg-ink-50 p-4">
            <p className="text-sm text-ink-600">You are joining</p>
            <p className="mt-1 text-lg font-semibold text-ink-950">{preview.workspace}</p>
            <p className="text-sm text-ink-600">
              {preview.organization}
              {preview.admin ? ` · admin ${preview.admin}` : ""}
            </p>
          </div>
          {error && <Alert>{error}</Alert>}
          <div className="flex gap-2">
            <Button busy={busy} onClick={join}>
              Request to join
            </Button>
            <Button variant="secondary" onClick={() => setPreview(null)}>
              Use another code
            </Button>
          </div>
        </div>
      ) : (
        <form
          className="mt-6 space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            void check();
          }}
        >
          <CodeInput length={32} value={code} onChange={setCode} />
          {error && <Alert>{error}</Alert>}
          <Button type="submit" busy={busy} disabled={!code || codeProblem(code, 32) !== null}>
            Continue
          </Button>
        </form>
      )}
    </Card>
  );
}

function Pending({ me }: { me: Me }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const m = me.membership!;
  const approver = m.role === "admin" ? "the organization's Super Admin" : "the workspace admin";
  const suspended = m.status === "suspended" || m.workspace?.status === "frozen" || m.organization.status !== "active";
  async function withdraw() {
    setBusy(true);
    try {
      await api.del("onboarding/request");
      router.refresh();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }
  return (
    <Card className="p-8 text-center">
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-amber-50 text-amber-600">
        <Clock className="size-6" aria-hidden />
      </div>
      {suspended ? (
        <>
          <h1 className="mt-4 text-xl font-semibold text-ink-950">Access is paused</h1>
          <p className="mt-2 text-sm text-ink-500">
            Your access to {m.workspace?.name ?? m.organization.name} is suspended. Contact {approver} to restore it.
          </p>
        </>
      ) : (
        <>
          <h1 className="mt-4 text-xl font-semibold text-ink-950">Waiting for approval</h1>
          <p className="mt-2 text-sm text-ink-500">
            Your request to join {m.workspace?.name ? `${m.workspace.name} at ` : ""}
            {m.organization.name} was sent to {approver}. You will have access as soon as it is approved.
          </p>
        </>
      )}
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-6 flex justify-center gap-2">
        <Button variant="secondary" onClick={() => router.refresh()}>
          Check again
        </Button>
        {m.status === "pending" && (
          <Button variant="ghost" busy={busy} onClick={withdraw}>
            Withdraw request
          </Button>
        )}
      </div>
    </Card>
  );
}
