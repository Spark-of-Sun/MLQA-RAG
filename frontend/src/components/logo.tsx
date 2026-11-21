import { BRAND } from "@/lib/format";

export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  const box = size === "lg" ? "size-9 text-base" : "size-7 text-sm";
  return (
    <div className="flex items-center gap-2">
      <div className={`flex ${box} items-center justify-center rounded-lg bg-ink-900 font-bold text-white`}>
        <span aria-hidden>§</span>
      </div>
      <span className={`font-semibold tracking-tight text-ink-950 ${size === "lg" ? "text-xl" : "text-base"}`}>{BRAND}</span>
    </div>
  );
}
