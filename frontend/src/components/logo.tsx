import { BRAND, COMPANY } from "@/lib/format";

/** The product mark. `company` adds "by" and the Onekami logo for public pages. */
export function Logo({ size = "md", company = false }: { size?: "md" | "lg"; company?: boolean }) {
  const box = size === "lg" ? "size-9 text-base" : "size-7 text-sm";
  return (
    <div className="flex items-center gap-2">
      <div className={`flex ${box} items-center justify-center rounded-lg bg-ink-900 font-bold text-white`}>
        <span aria-hidden>§</span>
      </div>
      <span className={`font-semibold tracking-tight text-ink-950 ${size === "lg" ? "text-xl" : "text-base"}`}>{BRAND}</span>
      {company && (
        <span className="hidden items-center gap-1.5 text-xs font-medium text-ink-400 sm:flex">
          by <CompanyMark className="h-3.5" />
        </span>
      )}
    </div>
  );
}

/** The company logo supplied in frontend/images, trimmed with a transparent background (public/onekami-logo.png). */
export function CompanyMark({ className = "h-8" }: { className?: string }) {
  // A plain img: the file is small and static, and the strict CSP already allows same-origin images.
  return <img src="/onekami-logo.png" alt={COMPANY} width={480} height={170} className={`${className} w-auto`} />;
}
