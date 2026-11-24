import { CompanyByline } from "@/components/site/company-byline";
import { BRAND, COMPANY } from "@/lib/format";

/**
 * The Cyte mark: the red brush ensō and orange star of the product icon (frontend/images/onekami-product.png),
 * lifted off its cream tile onto a transparent background by scripts/make-cyte-mark.py (public/cyte-mark.png, and
 * public/cyte-mark-64.png for small sizes). Deep red loses contrast on near-black, so dark mode shows the mark on a
 * small paper plate, like the icon's own tile and like the Onekami logo below: the mark keeps its own colors
 * instead of being recolored or inverted.
 */
export function CyteMark({ className = "h-7", small = false }: { className?: string; small?: boolean }) {
  const [src, w, h] = small ? ["/cyte-mark-64.png", 64, 64] : ["/cyte-mark.png", 255, 256];
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-md dark:bg-plate dark:p-0.5">
      {/* A plain img: the file is small and static, and the strict CSP already allows same-origin images. */}
      {/* eslint-disable-next-line @next/next/no-img-element -- a 10 KB static mark; no optimizer round-trip needed */}
      <img src={src} alt="" width={w} height={h} className={`${className} w-auto`} />
    </span>
  );
}

/**
 * The product logo (mark and wordmark). `company` adds "by" and the Onekami logo for public pages, except the
 * homepage, where CompanyByline hides it.
 */
export function Logo({ size = "md", company = false }: { size?: "md" | "lg"; company?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <CyteMark className={size === "lg" ? "h-8" : "h-6"} small={size !== "lg"} />
      <span className={`font-semibold tracking-tight text-ink-950 ${size === "lg" ? "text-xl" : "text-base"}`}>{BRAND}</span>
      {company && (
        <CompanyByline>
          <span className="hidden items-center gap-1.5 text-xs font-medium text-ink-500 sm:flex">
            by <CompanyMark className="h-3.5" />
          </span>
        </CompanyByline>
      )}
    </div>
  );
}

/**
 * The company logo supplied in frontend/images, trimmed with a transparent background (public/onekami-logo.png).
 * Its black lettering would disappear on a dark background, so dark mode shows it on a small light plate: the logo
 * keeps its own colors (the red sun included) instead of being recolored or inverted.
 */
export function CompanyMark({ className = "h-8" }: { className?: string }) {
  return (
    <span className="inline-flex items-center rounded-md dark:bg-plate dark:px-1.5 dark:py-1">
      {/* eslint-disable-next-line @next/next/no-img-element -- a small static logo, as above */}
      <img src="/onekami-logo.png" alt={COMPANY} width={480} height={170} className={`${className} w-auto`} />
    </span>
  );
}
