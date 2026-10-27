"use client";

import * as React from "react";
import { UploadCloud, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "../ui/Button";

interface UploadDropzoneProps {
  onUploadComplete?: () => void;
}

export function UploadDropzone({ onUploadComplete }: UploadDropzoneProps) {
  const [isUploading, setIsUploading] = React.useState(false);
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      return;
    }

    setIsUploading(true);
    setStatusMessage(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/documents", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error(`Upload failed with status: ${res.status}`);
      }

      const data = await res.json();
      setStatusMessage(`Success: ${data.message || "File uploaded and queued for processing"}`);
      onUploadComplete?.();
    } catch (err) {
      setStatusMessage(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  return (
    <div className="rounded-lg border-2 border-dashed border-slate-300 p-8 text-center hover:border-slate-400 transition-colors bg-white">
      <UploadCloud className="mx-auto h-12 w-12 text-slate-400" />
      <h3 className="mt-2 text-sm font-semibold text-slate-900">Upload Legal Agreement or Contract</h3>
      <p className="mt-1 text-xs text-slate-500">PDF, TXT, or HTML text layer up to 50MB. Scanned documents require usable text layer in MVP-A.</p>

      <div className="mt-6 flex justify-center">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,.html"
          onChange={handleFileChange}
          className="hidden"
          id="file-upload"
          disabled={isUploading}
        />
        <label htmlFor="file-upload">
          <Button
            type="button"
            isLoading={isUploading}
            onClick={() => fileInputRef.current?.click()}
          >
            Select Document
          </Button>
        </label>
      </div>

      {statusMessage && (
        <div className={`mt-4 inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded ${
          statusMessage.startsWith("Success")
            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
            : "bg-rose-50 text-rose-700 border border-rose-200"
        }`}>
          {statusMessage.startsWith("Success") ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : (
            <AlertCircle className="h-4 w-4" />
          )}
          <span>{statusMessage}</span>
        </div>
      )}
    </div>
  );
}
