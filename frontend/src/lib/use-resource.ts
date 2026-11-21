"use client";

import { useEffect, useEffectEvent, useState } from "react";

/**
 * Load data from the BFF, optionally polling, and reload on demand. State is only set after an await
 * (never synchronously in the effect body), which is what React's rules require. A response that
 * arrives after the component unmounted, or after a newer request started, is ignored.
 */
export function useResource<T>(fetcher: () => Promise<T>, pollMs?: number): readonly [T | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [tick, setTick] = useState(0);
  const run = useEffectEvent(fetcher);

  useEffect(() => {
    let live = true;
    void run()
      .then((value) => {
        if (live) setData(value);
      })
      .catch(() => undefined); // a 401 already navigated away; other errors keep the previous data on screen
    return () => {
      live = false;
    };
  }, [tick]);

  useEffect(() => {
    if (!pollMs) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), pollMs);
    return () => window.clearInterval(timer);
  }, [pollMs]);

  return [data, () => setTick((t) => t + 1)] as const;
}
