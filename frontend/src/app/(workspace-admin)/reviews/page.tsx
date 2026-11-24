import type { Metadata } from "next";

import { Reviews } from "@/components/manage/reviews";

export const metadata: Metadata = { title: "Review queue" };

export default function ReviewsPage() {
  return <Reviews />;
}
