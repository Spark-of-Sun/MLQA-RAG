"use client";

import { useEffect, useRef, useState } from "react";

/** Counts from 0 to `to` when it first scrolls into view. The server renders the final value. */
export function CountUp({ to, ms = 1200 }: { to: number; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(to);

  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        io.disconnect();
        const start = performance.now();
        const step = (now: number) => {
          const p = Math.min(1, (now - start) / ms);
          setValue(Math.round(to * (1 - Math.pow(1 - p, 3))));
          if (p < 1) frame = requestAnimationFrame(step);
        };
        setValue(0);
        frame = requestAnimationFrame(step);
      },
      { threshold: 0.6 },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [to, ms]);

  return (
    <span ref={ref} className="tabular-nums">
      {value}
    </span>
  );
}
