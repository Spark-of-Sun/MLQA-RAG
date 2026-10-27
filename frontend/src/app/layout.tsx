import type { Metadata } from "next";
import "./globals.css";
import { Navbar } from "@/components/ui/Navbar";

export const metadata: Metadata = {
  title: "MLQA-RAG | Multi-Tenant Legal & Medical Document Q&A",
  description: "Enterprise multi-tenant document intelligence with sentence-level citation verification.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 antialiased flex flex-col">
        <Navbar />
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
