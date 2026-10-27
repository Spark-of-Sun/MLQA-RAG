"use client";

import { X, FileText, CheckCircle2 } from "lucide-react";
import type { CitationHighlight } from "@/lib/sse";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";

interface CitationPanelProps {
  citation: CitationHighlight | null;
  onClose: () => void;
}

export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  if (!citation) {
    return (
      <aside className="w-80 border-l border-slate-200 bg-slate-50/50 p-6 flex flex-col justify-center items-center text-center text-slate-400">
        <FileText className="h-10 w-10 mb-3 opacity-40" />
        <p className="text-sm font-medium">Click any citation marker in an answer proposition to inspect chunk provenance.</p>
      </aside>
    );
  }

  return (
    <aside className="w-96 border-l border-slate-200 bg-white p-6 flex flex-col shadow-sm">
      <div className="flex items-center justify-between pb-4 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-emerald-600" />
          <h3 className="font-semibold text-slate-900 text-sm">Verified Source Provenance</h3>
        </div>
        <Button variant="outline" size="sm" onClick={onClose} aria-label="Close citation details">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="mt-4 space-y-4 flex-1 overflow-y-auto">
        <div>
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Document</label>
          <p className="text-sm font-medium text-slate-900 mt-0.5">{citation.docTitle}</p>
          <p className="text-xs text-slate-500 font-mono mt-0.5">{citation.docId}</p>
        </div>

        {citation.sectionTitle && (
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Section</label>
            <p className="text-sm text-slate-800 mt-0.5">{citation.sectionTitle}</p>
          </div>
        )}

        <div className="flex items-center gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Pages</label>
            <p className="text-sm font-medium text-slate-800 mt-0.5">{citation.pageRange || "p. 1"}</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Match Score</label>
            <div className="mt-0.5">
              <Badge variant="success">{(citation.confidenceScore * 100).toFixed(1)}% verified</Badge>
            </div>
          </div>
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Chunk Evidence Span</label>
          <div className="mt-1 p-3 rounded-md bg-slate-50 border border-slate-200 font-serif text-xs leading-relaxed text-slate-800 italic">
            "{citation.highlightSpan || "Exact textual chunk match verified by deterministic validator engine."}"
          </div>
        </div>

        <div className="pt-2 border-t border-slate-100">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Chunk Identifier</label>
          <p className="text-xs font-mono text-slate-600 mt-0.5">{citation.chunkId}</p>
        </div>
      </div>
    </aside>
  );
}
