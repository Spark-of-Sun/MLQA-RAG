import type { Metadata } from "next";
import { Public_Sans, Source_Serif_4 } from "next/font/google";
import { APP_NAME, APP_TAGLINE } from "@/lib/site";
import "./globals.css";

// Two families, clearly distinct roles: Public Sans (built for government
// digital-service clarity) carries every working UI surface; Source Serif 4
// is reserved for the wordmark and page titles, echoing the contract/
// clinical-note heritage of the documents this product reads.
const publicSans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-public-sans",
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: `${APP_NAME} — ${APP_TAGLINE}`,
  description:
    "Cited question answering over legal and medical documents, with every citation machine-verified before it reaches you.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${publicSans.variable} ${sourceSerif.variable}`}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
