import { Shell } from "@/components/Shell";
import { Walls } from "@/components/Walls";
import { requireMe } from "@/lib/guard";

export const dynamic = "force-dynamic";

export default async function WallsPage() {
  const me = await requireMe("/walls");
  return (
    <Shell me={me}>
      <h1 className="mb-4 text-xl font-semibold">Ethical walls</h1>
      <Walls />
    </Shell>
  );
}
