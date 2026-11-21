import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import type { ReactNode } from "react";

import { BRAND, COMPANY } from "@/lib/format";
import { THEME_COOKIE, parseTheme } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: `${BRAND} · cited answers from your documents`, template: `%s · ${BRAND}` },
  description: "Questions over legal and medical documents, answered only with verified, page-level citations.",
  applicationName: BRAND,
  authors: [{ name: COMPANY }],
  // Files in public/ (the icon set supplied in frontend/images); the manifest comes from app/manifest.ts.
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
    ],
    apple: { url: "/apple-touch-icon.png", sizes: "180x180" },
  },
};

// The browser's own UI (mobile address bar, window title bar) follows the system setting.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fcfcfc" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0b0e" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Reading the request headers opts every page into dynamic rendering, which the per-request CSP nonce needs.
  await headers();
  // The saved choice is rendered into the HTML, so the page is drawn in the right theme from the first frame. No
  // choice yet: no class, and the stylesheet follows the operating system (globals.css).
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);
  return (
    <html lang="en" className={theme ?? undefined}>
      <body>{children}</body>
    </html>
  );
}
