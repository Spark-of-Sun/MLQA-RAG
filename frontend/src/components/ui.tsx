"use client";

import { Loader2, X } from "lucide-react";
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "border border-ink-200 bg-white text-ink-800 hover:bg-ink-50 disabled:text-ink-400",
  ghost: "text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:text-ink-300",
  danger: "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50 disabled:text-rose-300",
};

export function Button({
  variant = "primary",
  busy = false,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-ink-200 bg-white shadow-sm ${className}`}>{children}</section>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink-950">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-ink-500">{subtitle}</p>}
      </div>
      {actions}
    </header>
  );
}

const TONES = {
  gray: "bg-ink-100 text-ink-700 ring-ink-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  blue: "bg-brand-50 text-brand-700 ring-brand-200",
} as const;

export function Badge({ tone = "gray", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "active" || status === "ready"
      ? "green"
      : status === "pending" || status === "processing"
        ? "amber"
        : status === "suspended" || status === "failed" || status === "frozen"
          ? "red"
          : "gray";
  return <Badge tone={tone}>{status}</Badge>;
}

export function Alert({ tone = "red", children }: { tone?: "red" | "amber" | "green" | "blue"; children: ReactNode }) {
  const styles = {
    red: "border-rose-200 bg-rose-50 text-rose-800",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    green: "border-emerald-200 bg-emerald-50 text-emerald-800",
    blue: "border-brand-200 bg-brand-50 text-brand-900",
  }[tone];
  return (
    <div role={tone === "red" ? "alert" : "status"} className={`rounded-lg border px-3.5 py-2.5 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-500">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-full bg-ink-100 p-3 text-ink-500">{icon}</div>
      <p className="font-medium text-ink-800">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-ink-500">{children}</div>}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 p-4" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl bg-white shadow-xl outline-none"
      >
        <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4">
          <h2 className="font-semibold text-ink-950">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-400 hover:bg-ink-100" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

/** A destructive action that asks for confirmation inline, without a native dialog. */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  variant = "danger",
}: {
  label: string;
  confirmLabel?: string;
  onConfirm: () => Promise<void> | void;
  variant?: Variant;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Button
      variant={armed ? "danger" : variant}
      busy={busy}
      className="px-2.5 py-1.5 text-xs"
      onClick={async () => {
        if (!armed) return setArmed(true);
        setBusy(true);
        try {
          await onConfirm();
        } finally {
          setBusy(false);
          setArmed(false);
        }
      }}
    >
      {armed ? (confirmLabel ?? `Confirm ${label.toLowerCase()}`) : label}
    </Button>
  );
}
