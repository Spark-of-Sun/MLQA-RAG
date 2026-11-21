import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { BRAND } from "@/lib/format";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: `${BRAND} · cited answers from your documents`, template: `%s · ${BRAND}` },
  description: "Questions over legal and medical documents, answered only with verified, page-level citations.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Reading the request headers opts every page into dynamic rendering, which the per-request CSP nonce needs.
  await headers();
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
