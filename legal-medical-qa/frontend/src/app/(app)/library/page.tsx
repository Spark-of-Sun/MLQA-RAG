import { Library } from "@/components/Library";
import { Shell } from "@/components/Shell";
import { requireMe } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function LibraryPage() {
  const me = await requireMe("/library");
  return (
    <Shell me={me}>
      <Library />
    </Shell>
  );
}
