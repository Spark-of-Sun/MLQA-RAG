"use client";

import { ClipboardCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, Button, EmptyState, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api-client";
import { formatDate } from "@/lib/format";

interface ReviewRow {
  id: string;
  kind: string;
  subject_id: string;
  state: "open" | "closed";
  due_at: string;
  created_at: string;
}

const KIND_LABEL: Record<string, string> = {
  emergency_access: "Emergency access",
  break_glass: "Break-glass session",
  ocr_review: "OCR review",
  citation_failure: "Citation failure",
};

export function Reviews() {
  const [rows, setRows] = useState<ReviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<ReviewRow | null>(null);
  const [outcome, setOutcome] = useState("");

  const load = useCallback(async () => {
    try {
      setRows(await api.get<ReviewRow[]>("reviews"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function close() {
    if (!closing) return;
    try {
      await api.post(`reviews/${closing.id}/close`, { outcome });
      setClosing(null);
      setOutcome("");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const overdue = (r: ReviewRow) => r.state === "open" && new Date(r.due_at).getTime() < Date.now();
  return (
    <div>
      <PageHeader title="Review queue" subtitle="Every emergency access must be reviewed within 72 hours; overdue items alert at 48 and 72 hours." />
      {error && <Alert>{error}</Alert>}
      {rows === null ? <Spinner label="Loading reviews" /> : rows.length === 0 ? (
        <EmptyState icon={<ClipboardCheck aria-hidden />} title="Nothing to review" />
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead><tr className="text-left text-ink-500"><th className="py-2">Item</th><th>Opened</th><th>Due</th><th>State</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-ink-100">
                <td className="py-2">{KIND_LABEL[r.kind] ?? r.kind}</td>
                <td>{formatDate(r.created_at)}</td>
                <td className={overdue(r) ? "font-medium text-rose-700" : ""}>{formatDate(r.due_at)}{overdue(r) ? " (overdue)" : ""}</td>
                <td><StatusBadge status={r.state} /></td>
                <td className="text-right">{r.state === "open" && <Button variant="secondary" onClick={() => { setClosing(r); }}>Close</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {closing && (
        <Modal title={`Close: ${KIND_LABEL[closing.kind] ?? closing.kind}`} onClose={() => { setClosing(null); }}>
          <label className="block text-sm font-medium text-ink-700" htmlFor="review-outcome">Outcome</label>
          <textarea id="review-outcome" className="mt-1 w-full rounded-md border border-ink-200 p-2 text-sm" rows={4}
            value={outcome} maxLength={2000} onChange={(e) => { setOutcome(e.target.value); }} />
          <Button className="mt-3" disabled={outcome.trim().length < 3} onClick={() => void close()}>Record and close</Button>
        </Modal>
      )}
    </div>
  );
}
