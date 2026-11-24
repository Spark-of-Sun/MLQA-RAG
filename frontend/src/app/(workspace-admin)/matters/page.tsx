import type { Metadata } from "next";

import { Matters } from "@/components/manage/matters";

export const metadata: Metadata = { title: "Matters and walls" };

export default function MattersPage() {
  return <Matters />;
}
