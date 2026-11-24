"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** Shows the "by Onekami" byline in the site header on every public page except the homepage. */
export function CompanyByline({ children }: { children: ReactNode }) {
  return usePathname() === "/" ? null : <>{children}</>;
}
