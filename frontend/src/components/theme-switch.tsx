"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { THEME_COOKIE, type Theme } from "@/lib/theme";

// A light/dark slider. The thumb position and colors come from the `dark:` variant, so the switch is drawn
// correctly from the server-rendered HTML, before any JavaScript runs; JavaScript only handles the click and keeps
// `aria-checked` in step. The choice is saved in a cookie (read by app/layout.tsx) for a year.

const SYSTEM_DARK = "(prefers-color-scheme: dark)";

function isDark(): boolean {
  const root = document.documentElement;
  if (root.classList.contains("dark")) return true;
  if (root.classList.contains("light")) return false;
  return window.matchMedia(SYSTEM_DARK).matches;
}

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  const media = window.matchMedia(SYSTEM_DARK);
  media.addEventListener("change", onChange);
  return () => {
    observer.disconnect();
    media.removeEventListener("change", onChange);
  };
}

function apply(theme: Theme): void {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  root.classList.add(theme);
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${THEME_COOKIE}=${theme}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
}

export function ThemeSwitch({ className = "" }: { className?: string }) {
  // Every instance on the page (for example the header and a menu) stays in step through the <html> class.
  const dark = useSyncExternalStore(subscribe, isDark, () => false);

  function toggle() {
    const next: Theme = isDark() ? "light" : "dark";
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduce && "startViewTransition" in document) {
      document.startViewTransition(() => { apply(next); });
    } else {
      apply(next);
    }
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark mode"
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggle}
      className={`relative inline-flex h-7 w-[52px] shrink-0 items-center rounded-full border border-ink-200 bg-ink-100 transition-colors hover:border-ink-300 dark:border-brand-400/40 dark:bg-brand-100 ${className}`}
    >
      <Sun className="absolute left-1.5 size-3.5 text-amber-500 opacity-0 transition-opacity dark:opacity-60" aria-hidden />
      <Moon className="absolute right-1.5 size-3.5 text-ink-400 transition-opacity dark:opacity-0" aria-hidden />
      <span className="flex size-[22px] translate-x-[2px] items-center justify-center rounded-full bg-surface shadow-sm ring-1 ring-ink-200 transition-transform duration-300 ease-out dark:translate-x-[26px] dark:bg-raised dark:ring-brand-400/50">
        <Sun className="size-3.5 text-amber-500 dark:hidden" aria-hidden />
        <Moon className="hidden size-3.5 text-brand-700 dark:block" aria-hidden />
      </span>
    </button>
  );
}
