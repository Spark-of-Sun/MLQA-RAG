export const BRAND = "Cyte"; // the product
export const COMPANY = "Onekami"; // the company that makes it
export const CONTACT_EMAIL = "contact@onekami.site"; // sales, demos and general questions
export const SUPPORT_EMAIL = "info@onekami.site"; // help for customers using the product

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDay(iso);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function pages(start: number | null, end: number | null): string {
  if (start == null) return "";
  return end != null && end !== start ? `pp. ${start}–${end}` : `p. ${start}`;
}

export const ROLE_LABEL = { super_admin: "Super Admin", admin: "Admin", tenant: "Member" } as const;

/** Token totals are approximate (model-reported prompt and output tokens; embeddings are not counted). */
export function formatTokens(n: number): string {
  if (n < 1000) return `≈${n}`;
  if (n < 1_000_000) return `≈${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `≈${(n / 1_000_000).toFixed(1)}M`;
}
