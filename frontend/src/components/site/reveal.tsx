"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/**
 * Fades elements marked `data-reveal` up as they scroll into view. Mounted once by the site layout; it runs again
 * after each client-side navigation so the new page's elements are observed too.
 */
export function Reveal() {
  const pathname = usePathname();
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const root = document.documentElement;
    root.classList.add("reveal-ready");
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          e.target.setAttribute("data-shown", "");
          io.unobserve(e.target);
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.1 },
    );
    document.querySelectorAll("[data-reveal]:not([data-shown])").forEach((el) => { io.observe(el); });
    return () => { io.disconnect(); };
  }, [pathname]);

  useEffect(() => () => { document.documentElement.classList.remove("reveal-ready"); }, []);
  return null;
}
