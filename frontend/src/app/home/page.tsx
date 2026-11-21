import { redirect } from "next/navigation";

import { homeFor, requireMe } from "@/lib/backend";

// Post-login dispatcher: sends each principal to its screen (blueprint 17.1).
export default async function Home() {
  redirect(homeFor(await requireMe()));
}
